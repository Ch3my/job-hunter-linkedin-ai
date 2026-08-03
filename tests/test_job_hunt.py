"""Orquestacion completa: API -> AI -> base de datos.

Los dobles son clases normales: como los puertos son `Protocol`, basta con
tener los mismos metodos. No hace falta libreria de mocking.
"""

import pytest

from ai.relevance import NOT_RELEVANT, RELEVANT, AlwaysRelevant
from db import create_table, insert_job, select_jobs
from models import JobPosting
from providers import ProviderError
from providers.base import FetchResult
from services import job_hunt


class FakeSource:
    """Doble de una API: devuelve los trabajos que le pasemos."""

    name = "fake"

    def __init__(self, postings=None, received=None, skipped=0, error=None):
        self.postings = postings or []
        self.received = len(self.postings) if received is None else received
        self.skipped = skipped
        self.error = error
        self.llamadas = 0

    def fetch(self):
        self.llamadas += 1
        if self.error:
            raise self.error
        return FetchResult(postings=list(self.postings), received=self.received, skipped=self.skipped)


class FakeClassifier:
    """Doble de la AI: rechaza los titulos que se le indiquen."""

    def __init__(self, rechazar=(), reventar=False):
        self.rechazar = set(rechazar)
        self.reventar = reventar
        self.vistos = []

    def classify(self, posting):
        if self.reventar:
            raise RuntimeError("LLM caido")
        self.vistos.append(posting.title)
        return NOT_RELEVANT if posting.title in self.rechazar else RELEVANT


def job(title, company="ACME"):
    return JobPosting(title=title, company=company, description="d")


@pytest.fixture(autouse=True)
def tabla():
    create_table()


class TestCorridaFeliz:
    def test_guarda_los_relevantes(self):
        source = FakeSource([job("A"), job("B")])
        report = job_hunt(source=source, classifier=FakeClassifier())
        assert report.inserted == 2
        assert len(select_jobs()) == 2
        assert not report.error

    def test_descarta_los_no_relevantes(self):
        source = FakeSource([job("A"), job("B")])
        report = job_hunt(source=source, classifier=FakeClassifier(rechazar=["B"]))
        assert report.inserted == 1
        assert report.not_relevant == 1
        assert [row[0] for row in select_jobs()] == ["A"]

    def test_no_duplica_en_una_segunda_corrida(self):
        source = FakeSource([job("A")])
        job_hunt(source=source, classifier=FakeClassifier())
        report = job_hunt(source=FakeSource([job("A")]), classifier=FakeClassifier())
        assert report.inserted == 0
        assert report.already_known == 1
        assert len(select_jobs()) == 1

    def test_no_gasta_tokens_en_trabajos_ya_guardados(self):
        """El chequeo en la DB va antes que la llamada al LLM."""
        insert_job(job("Ya guardado"))
        classifier = FakeClassifier()
        job_hunt(source=FakeSource([job("Ya guardado"), job("Nuevo")]), classifier=classifier)
        assert classifier.vistos == ["Nuevo"]

    def test_arrastra_los_contadores_de_la_api(self):
        report = job_hunt(source=FakeSource([job("A")], received=10, skipped=9),
                          classifier=FakeClassifier())
        assert report.received == 10
        assert report.skipped_by_api == 9

    def test_devuelve_los_trabajos_nuevos(self):
        report = job_hunt(source=FakeSource([job("A")]), classifier=FakeClassifier())
        assert [j.title for j in report.new_jobs] == ["A"]


class TestAislamientoDeErrores:
    def test_falla_de_api_se_reporta_sin_lanzar(self):
        report = job_hunt(source=FakeSource(error=ProviderError("429 rate limit")))
        assert report.error == "429 rate limit"
        assert report.inserted == 0
        assert "Error:" in report.message()

    def test_excepcion_inesperada_tampoco_lanza(self):
        report = job_hunt(source=FakeSource(error=ValueError("algo raro")))
        assert "inesperado" in report.error
        assert report.inserted == 0

    def test_falla_del_llm_no_corta_la_busqueda(self):
        report = job_hunt(source=FakeSource([job("A"), job("B")]),
                          classifier=FakeClassifier(reventar=True))
        assert report.failed == 2
        assert report.inserted == 0
        assert not report.error       # la app sigue viva

    def test_un_trabajo_malo_no_impide_guardar_los_demas(self):
        class ClassifierParcial:
            def classify(self, posting):
                if posting.title == "malo":
                    raise RuntimeError("boom")
                return RELEVANT

        report = job_hunt(source=FakeSource([job("bueno1"), job("malo"), job("bueno2")]),
                          classifier=ClassifierParcial())
        assert report.inserted == 2
        assert report.failed == 1
        assert sorted(row[0] for row in select_jobs()) == ["bueno1", "bueno2"]

    def test_respuesta_vacia_no_es_error(self):
        report = job_hunt(source=FakeSource([]), classifier=FakeClassifier())
        assert report.inserted == 0
        assert not report.error

    def test_callback_de_ui_defectuoso_no_rompe_nada(self):
        def callback_roto(mensaje):
            raise ZeroDivisionError

        report = job_hunt(source=FakeSource([job("A")]), classifier=FakeClassifier(),
                          on_status=callback_roto)
        assert report.inserted == 1
        assert not report.error


class TestProgresoYAvisos:
    def test_informa_progreso(self):
        vistos = []
        job_hunt(source=FakeSource([job("A"), job("B")]), classifier=FakeClassifier(),
                 on_status=vistos.append)
        assert any("Evaluando 1/2" in m for m in vistos)
        assert any("Consultando fake" in m for m in vistos)

    def test_avisa_cuando_la_ai_no_esta_filtrando(self):
        """Si no hay prompt.txt hay que decirlo, no fingir que filtro."""
        report = job_hunt(source=FakeSource([job("A")]),
                          classifier=AlwaysRelevant("no hay prompt.txt"))
        assert report.ai_notice == "no hay prompt.txt"
        assert "no hay prompt.txt" in report.message()

    def test_sin_aviso_el_mensaje_queda_limpio(self):
        report = job_hunt(source=FakeSource([job("A")]), classifier=FakeClassifier())
        assert "(" not in report.message()
        assert "1 nuevos" in report.message()


class TestConRespuestaRealDeLaApi:
    def test_flujo_completo_con_el_json_real(self, api_jobs):
        """Del JSON crudo de la API hasta las filas en sqlite."""
        from providers.base import map_items
        from providers.fantastic_linkedin import to_posting

        result = map_items(api_jobs, to_posting, "fantastic_linkedin")
        report = job_hunt(source=FakeSource(result.postings), classifier=FakeClassifier())

        assert report.inserted == len(api_jobs)
        filas = select_jobs()
        assert len(filas) == len(api_jobs)
        for titulo, empresa, estado, creado in filas:
            assert titulo and empresa
            assert estado == "Not applied"
            assert creado
