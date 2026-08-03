"""Lectura de la cuota que la API informa en las cabeceras.

Cada trabajo devuelto descuenta un credito de "jobs", asi que conviene ver
cuanto queda antes de toparse con un 429.
"""

import pytest

from providers.http import HttpClient


def client(**headers):
    http = HttpClient(host="h", headers={})
    http.last_headers = headers
    return http


class TestLecturaDeCuota:
    def test_lee_las_cuatro_cabeceras(self):
        q = client(**{
            "x-ratelimit-jobs-limit": "200000",
            "x-ratelimit-jobs-remaining": "199234",
            "x-ratelimit-requests-limit": "25000",
            "x-ratelimit-requests-remaining": "24975",
            "x-ratelimit-jobs-reset": "2505077",
        }).quota()
        assert q["jobs_remaining"] == 199234
        assert q["jobs_limit"] == 200000
        assert q["requests_remaining"] == 24975
        assert q["requests_limit"] == 25000
        assert q["reset_seconds"] == 2505077

    def test_sin_cabeceras_devuelve_none(self):
        assert all(v is None for v in client().quota().values())

    def test_valores_no_numericos_no_lanzan(self):
        assert client(**{"x-ratelimit-jobs-remaining": "muchos"}).quota()["jobs_remaining"] is None

    def test_cabeceras_insensibles_a_mayusculas(self):
        """urllib puede devolverlas capitalizadas; se normalizan al guardar."""
        http = HttpClient(host="h", headers={})
        http.last_headers = {k.lower(): v for k, v in {"X-RateLimit-Jobs-Remaining": "5"}.items()}
        assert http.quota()["jobs_remaining"] == 5


class TestResumen:
    def test_texto_legible(self):
        resumen = client(**{
            "x-ratelimit-jobs-limit": "200000",
            "x-ratelimit-jobs-remaining": "199234",
            "x-ratelimit-requests-remaining": "24975",
            "x-ratelimit-jobs-reset": "2505077",
        }).quota_summary()
        assert "jobs 199234/200000" in resumen
        assert "requests 24975" in resumen
        assert "renueva en 28d" in resumen

    def test_sin_cabeceras_no_inventa_nada(self):
        assert client().quota_summary() == ""

    def test_parcial_muestra_lo_que_hay(self):
        assert client(**{"x-ratelimit-jobs-remaining": "10"}).quota_summary() == "cuota restante: jobs 10"


class TestCuotaAgotada:
    """Con un contador en cero, reintentar no sirve: hay que fallar rapido."""

    @pytest.mark.parametrize(
        "headers,queda",
        [
            ({"x-ratelimit-requests-remaining": "0"}, False),
            ({"x-ratelimit-jobs-remaining": "0"}, False),
            ({"x-ratelimit-requests-remaining": "5"}, True),
            ({"x-ratelimit-jobs-remaining": "172", "x-ratelimit-requests-remaining": "0"}, False),
            ({}, True),   # sin cabeceras no se asume nada
        ],
    )
    def test_detecta_cuota_agotada(self, headers, queda):
        assert client(**headers)._quota_left() is queda

    def test_el_caso_real_del_plan_basic(self):
        """Se acabaron los requests aunque quedaran jobs disponibles."""
        http = client(**{
            "x-ratelimit-jobs-limit": "250",
            "x-ratelimit-jobs-remaining": "172",
            "x-ratelimit-requests-limit": "25",
            "x-ratelimit-requests-remaining": "0",
        })
        assert http._quota_left() is False
        assert "requests 0/25" in http.quota_summary()
        assert "jobs 172/250" in http.quota_summary()


class TestLlegaAlReporte:
    def test_el_reporte_incluye_la_cuota(self):
        from db import create_table
        from models import JobPosting
        from providers.base import FetchResult
        from services import job_hunt

        create_table()

        class SourceConCuota:
            name = "fake"

            def fetch(self):
                return FetchResult(
                    postings=[JobPosting(title="T", company="C", description="d")],
                    received=1,
                    quota="cuota restante: jobs 150/200",
                )

        class SiempreRelevante:
            def classify(self, posting):
                return "relevante"

        vistos = []
        report = job_hunt(source=SourceConCuota(), classifier=SiempreRelevante(),
                          on_status=vistos.append)
        assert report.quota == "cuota restante: jobs 150/200"
        assert "[cuota restante: jobs 150/200]" in report.message()
        assert any("cuota restante" in m for m in vistos)

    def test_sin_cuota_el_mensaje_queda_limpio(self):
        from db import create_table
        from models import JobPosting
        from providers.base import FetchResult
        from services import job_hunt

        create_table()

        class SourceSinCuota:
            name = "fake"

            def fetch(self):
                return FetchResult(postings=[JobPosting(title="T", company="C")], received=1)

        class SiempreRelevante:
            def classify(self, posting):
                return "relevante"

        assert "[" not in job_hunt(source=SourceSinCuota(), classifier=SiempreRelevante()).message()
