"""Clasificacion de relevancia y uso de prompt.txt.

No se llama a OpenAI: se inyectan modulos falsos de langchain para capturar
exactamente que mensajes se enviarian.
"""

import sys
import types

import pytest

from ai import AlwaysRelevant, Verdict, as_verdict, create_classifier, is_relevant
from ai.relevance import NOT_EVALUATED, NOT_RELEVANT, RELEVANT, OpenAIRelevanceClassifier
from models import JobPosting

PERFIL = "Soy contador. Habilidades: auditoría, análisis financiero, asesoría fiscal."


@pytest.fixture
def fake_langchain(monkeypatch):
    """Reemplaza langchain por dobles y devuelve lo capturado."""
    capturado = {}

    class FakeChain:
        def __init__(self, messages):
            self.messages = messages

        def __or__(self, other):
            return self

        def invoke(self, variables):
            capturado["variables"] = variables
            return capturado.get("respuesta", {"score": 90, "reason": "calza"})

    class FakeTemplate:
        @staticmethod
        def from_messages(messages):
            capturado["messages"] = messages
            return FakeChain(messages)

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            capturado["llm_kwargs"] = kwargs

        def with_structured_output(self, schema, **kwargs):
            capturado["schema"] = schema
            return self

    prompts = types.ModuleType("langchain_core.prompts")
    prompts.ChatPromptTemplate = FakeTemplate
    openai = types.ModuleType("langchain_openai")
    openai.ChatOpenAI = FakeChatOpenAI

    monkeypatch.setitem(sys.modules, "langchain_core", types.ModuleType("langchain_core"))
    monkeypatch.setitem(sys.modules, "langchain_core.prompts", prompts)
    monkeypatch.setitem(sys.modules, "langchain_openai", openai)
    return capturado


@pytest.fixture
def con_prompt(workdir):
    (workdir / "prompt.txt").write_text(PERFIL, encoding="utf-8")


class TestSeleccionDeClasificador:
    def test_sin_prompt_txt_no_filtra_pero_avisa(self):
        classifier = create_classifier()
        assert isinstance(classifier, AlwaysRelevant)
        assert "No se encontro" in classifier.reason

    def test_prompt_vacio_tambien_avisa(self, workdir):
        (workdir / "prompt.txt").write_text("   \n  ", encoding="utf-8")
        assert isinstance(create_classifier(), AlwaysRelevant)

    def test_el_aviso_queda_en_el_log(self, workdir):
        create_classifier()
        assert "SIN FILTRO AI" in (workdir / "log.txt").read_text(encoding="utf-8")

    def test_con_prompt_txt_usa_el_llm(self, con_prompt, fake_langchain):
        assert isinstance(create_classifier(), OpenAIRelevanceClassifier)

    def test_si_falta_langchain_degrada_sin_romper(self, con_prompt, monkeypatch):
        monkeypatch.setitem(sys.modules, "langchain_openai", None)
        classifier = create_classifier()
        assert isinstance(classifier, AlwaysRelevant)
        assert classifier.classify(JobPosting(title="T", company="C")) == RELEVANT


class TestArmadoDelPrompt:
    def test_el_perfil_va_en_su_propio_mensaje(self, con_prompt, fake_langchain):
        create_classifier()
        roles = [role for role, _ in fake_langchain["messages"]]
        assert roles == ["system", "user", "user"]

        _, system_text = fake_langchain["messages"][0]
        _, perfil_text = fake_langchain["messages"][1]
        assert "score" in system_text
        assert perfil_text == PERFIL
        assert "auditoría" in perfil_text

    def test_la_oferta_va_aparte_y_delimitada(self, con_prompt, fake_langchain):
        """El texto de la oferta es ajeno: no puede leerse como instrucciones."""
        create_classifier()
        _, oferta_text = fake_langchain["messages"][2]
        assert "<oferta>" in oferta_text and "</oferta>" in oferta_text
        assert "{job}" in oferta_text
        assert PERFIL not in oferta_text

    def test_pide_la_respuesta_estructurada(self, con_prompt, fake_langchain):
        create_classifier()
        schema = fake_langchain["schema"]
        assert schema["required"] == ["score", "reason"]
        assert schema["properties"]["score"]["type"] == "integer"

    def test_usa_el_modelo_configurado(self, con_prompt, fake_langchain):
        from ai.relevance import DEFAULT_MODEL

        create_classifier()
        assert fake_langchain["llm_kwargs"]["model"] == DEFAULT_MODEL

    def test_no_fuerza_temperature(self, con_prompt, fake_langchain):
        """gpt-5-mini solo acepta la temperatura por defecto."""
        create_classifier()
        assert "temperature" not in fake_langchain["llm_kwargs"]

    def test_el_trabajo_llega_con_contexto(self, con_prompt, fake_langchain):
        classifier = create_classifier()
        classifier.classify(JobPosting(
            title="Contador Auditor", company="ACME", location="Santiago",
            employment_type="FULL_TIME", description="Se busca contador con SAP."))
        enviado = fake_langchain["variables"]["job"]
        assert "Cargo: Contador Auditor" in enviado
        assert "Empresa: ACME" in enviado
        assert "Ubicacion: Santiago" in enviado
        assert "SAP" in enviado

    def test_trabajo_sin_descripcion_igual_se_evalua(self, con_prompt, fake_langchain):
        create_classifier().classify(JobPosting(title="Analista", company="Beta"))
        enviado = fake_langchain["variables"]["job"]
        assert "Cargo: Analista" in enviado
        assert "sin descripcion" in enviado


class TestPuntajeYCorte:
    """El LLM puntua; el corte (minScore) decide. Default: 60."""

    def clasificar(self, fake, score, reason="porque si"):
        fake["respuesta"] = {"score": score, "reason": reason}
        return create_classifier().classify(JobPosting(title="T", company="C"))

    @pytest.mark.parametrize(
        "score,esperado",
        [(0, NOT_RELEVANT), (59, NOT_RELEVANT), (60, RELEVANT), (95, RELEVANT)],
    )
    def test_el_corte_decide(self, con_prompt, fake_langchain, score, esperado):
        assert self.clasificar(fake_langchain, score).label == esperado

    def test_conserva_puntaje_y_motivo(self, con_prompt, fake_langchain):
        verdict = self.clasificar(fake_langchain, 82, "calza con nutricion clinica")
        assert verdict.score == 82
        assert verdict.reason == "calza con nutricion clinica"

    def test_el_corte_es_configurable(self, con_prompt, fake_langchain, workdir):
        (workdir / "config.json").write_text('{"ai": {"minScore": 90}}', encoding="utf-8")
        assert self.clasificar(fake_langchain, 80).label == NOT_RELEVANT

    def test_un_corte_invalido_cae_al_default(self, con_prompt, fake_langchain, workdir):
        (workdir / "config.json").write_text('{"ai": {"minScore": "muy alto"}}', encoding="utf-8")
        assert create_classifier().threshold == 60

    @pytest.mark.parametrize("score,esperado", [(-20, 0), (500, 100)])
    def test_acota_puntajes_fuera_de_rango(self, con_prompt, fake_langchain, score, esperado):
        assert self.clasificar(fake_langchain, score).score == esperado


class TestAnteLaDudaPasa:
    """Nunca se descarta un trabajo por un problema tecnico."""

    def test_si_el_llm_revienta_no_se_pierde_el_trabajo(self, con_prompt, fake_langchain):
        classifier = create_classifier()

        class Boom:
            def invoke(self, _):
                raise RuntimeError("rate limit")

        classifier.chain = Boom()
        verdict = classifier.classify(JobPosting(title="T", company="C"))
        assert verdict.label == RELEVANT
        assert verdict.score == NOT_EVALUATED
        assert "rate limit" in verdict.reason

    @pytest.mark.parametrize("respuesta", [{}, {"reason": "sin puntaje"}, {"score": None}, None, "texto"])
    def test_respuesta_ilegible_deja_pasar_el_trabajo(self, con_prompt, fake_langchain, respuesta):
        fake_langchain["respuesta"] = respuesta
        verdict = create_classifier().classify(JobPosting(title="T", company="C"))
        assert verdict.label == RELEVANT
        assert verdict.score == NOT_EVALUATED

    def test_sin_ai_el_veredicto_dice_que_no_se_evaluo(self):
        verdict = AlwaysRelevant("sin prompt").classify(JobPosting(title="T", company="C"))
        assert verdict.label == RELEVANT
        assert verdict.score == NOT_EVALUATED


class TestVerdict:
    def test_se_compara_con_el_string_de_siempre(self):
        assert Verdict(RELEVANT, 90, "x") == RELEVANT
        assert Verdict(NOT_RELEVANT, 10, "x") == NOT_RELEVANT

    def test_acepta_un_clasificador_que_devuelve_string(self):
        """Los dobles de test viejos siguen sirviendo."""
        assert as_verdict("no-relevante").relevant is False
        assert as_verdict("NO-RELEVANTE").relevant is False
        assert as_verdict(None).relevant is True

    @pytest.mark.parametrize(
        "valor,esperado",
        [
            ("relevante", True),
            ("no-relevante", False),
            ("NO-RELEVANTE", False),
            (None, True),
            ("", True),
            (Verdict(NOT_RELEVANT, 10, "x"), False),
            (Verdict(RELEVANT, 80, "x"), True),
        ],
    )
    def test_is_relevant(self, valor, esperado):
        assert is_relevant(valor) is esperado
