"""Clasificacion de relevancia y uso de prompt.txt.

No se llama a OpenAI: se inyectan modulos falsos de langchain para capturar
exactamente que mensajes se enviarian.
"""

import sys
import types

import pytest

from ai import AlwaysRelevant, create_classifier, is_relevant
from ai.relevance import NOT_RELEVANT, RELEVANT, OpenAIRelevanceClassifier
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
            return capturado.get("respuesta", "relevante")

    class FakeTemplate:
        @staticmethod
        def from_messages(messages):
            capturado["messages"] = messages
            return FakeChain(messages)

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            capturado["llm_kwargs"] = kwargs

    prompts = types.ModuleType("langchain_core.prompts")
    prompts.ChatPromptTemplate = FakeTemplate
    parsers = types.ModuleType("langchain_core.output_parsers")
    parsers.StrOutputParser = lambda: object()
    openai = types.ModuleType("langchain_openai")
    openai.ChatOpenAI = FakeChatOpenAI

    monkeypatch.setitem(sys.modules, "langchain_core", types.ModuleType("langchain_core"))
    monkeypatch.setitem(sys.modules, "langchain_core.prompts", prompts)
    monkeypatch.setitem(sys.modules, "langchain_core.output_parsers", parsers)
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
    def test_el_perfil_va_en_el_mensaje_del_usuario(self, con_prompt, fake_langchain):
        create_classifier()
        roles = [role for role, _ in fake_langchain["messages"]]
        assert roles == ["system", "user"]

        _, system_text = fake_langchain["messages"][0]
        _, user_text = fake_langchain["messages"][1]
        assert "no-relevante" in system_text
        assert user_text.startswith(PERFIL)
        assert user_text.endswith("{job}")
        assert "auditoría" in user_text

    def test_usa_el_modelo_configurado(self, con_prompt, fake_langchain):
        from ai.relevance import DEFAULT_MODEL

        create_classifier()
        assert fake_langchain["llm_kwargs"]["model"] == DEFAULT_MODEL

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


class TestRespuestas:
    @pytest.mark.parametrize(
        "respuesta,esperado",
        [
            ("relevante", RELEVANT),
            ("no-relevante", NOT_RELEVANT),
            ("  NO-RELEVANTE  ", NOT_RELEVANT),
            ("No-Relevante", NOT_RELEVANT),
            ("cualquier cosa", RELEVANT),
            ("", RELEVANT),
        ],
    )
    def test_normaliza_la_respuesta(self, con_prompt, fake_langchain, respuesta, esperado):
        fake_langchain["respuesta"] = respuesta
        assert create_classifier().classify(JobPosting(title="T", company="C")) == esperado

    def test_si_el_llm_revienta_no_se_pierde_el_trabajo(self, con_prompt, fake_langchain):
        classifier = create_classifier()

        class Boom:
            def invoke(self, _):
                raise RuntimeError("rate limit")

        classifier.chain = Boom()
        assert classifier.classify(JobPosting(title="T", company="C")) == RELEVANT

    @pytest.mark.parametrize(
        "valor,esperado",
        [("relevante", True), ("no-relevante", False), ("NO-RELEVANTE", False), (None, True), ("", True)],
    )
    def test_is_relevant(self, valor, esperado):
        assert is_relevant(valor) is esperado
