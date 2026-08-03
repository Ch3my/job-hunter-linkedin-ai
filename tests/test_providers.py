"""La capa de APIs: parametros, mapeo y aislamiento de datos malos.

`to_posting` es una funcion pura, asi que estos tests corren sin red usando el
JSON real guardado en tests/fixtures/.
"""

import pytest

from models import JobPosting
from providers import ProviderError, available_sources, create_source
from providers.base import FetchResult, JobSource, map_items
from providers.fantastic_linkedin import (
    ENDPOINT,
    SUPPORTED_PARAMS,
    FantasticLinkedInSource,
    _extract_items,
    to_posting,
)
from providers.linkedin_data_scraper import to_posting as legacy_to_posting


def source(**search):
    return FantasticLinkedInSource({"apiKey": "k", "search": search})


class TestRegistry:
    def test_proveedores_disponibles(self):
        assert available_sources() == ["fantastic_linkedin", "linkedin_data_scraper"]

    def test_crea_el_proveedor_activo(self, write_config):
        write_config({"rapidApiKey": "k"})
        assert create_source().name == "fantastic_linkedin"

    def test_se_puede_cambiar_de_api_por_config(self, write_config):
        write_config({"rapidApiKey": "k", "provider": "linkedin_data_scraper"})
        assert create_source().name == "linkedin_data_scraper"

    def test_proveedor_desconocido_da_error_claro(self, write_config):
        write_config({"rapidApiKey": "k"})
        with pytest.raises(ProviderError, match="desconocido"):
            create_source("no_existe")

    def test_sin_api_key_da_error_claro(self, write_config):
        write_config({"rapidApiKey": ""})
        with pytest.raises(ProviderError, match="rapidApiKey"):
            create_source()

    def test_los_proveedores_cumplen_el_protocolo(self, write_config):
        write_config({"rapidApiKey": "k"})
        assert isinstance(create_source(), JobSource)


class TestBuildParams:
    def test_endpoint_correcto(self):
        assert ENDPOINT == "active-jb"

    def test_defaults(self):
        params = source().build_params()
        assert params["time_frame"] == "24h"
        assert params["limit"] == 25
        assert params["offset"] == 0
        assert params["description_format"] == "text"

    def test_pasa_los_parametros_de_la_api_tal_cual(self):
        params = source(title="Contador Auditor", location="Chile", limit=10).build_params()
        assert params["title"] == "Contador Auditor"
        assert params["location"] == "Chile"
        assert params["limit"] == 10

    @pytest.mark.parametrize(
        "name",
        ["time_frame", "limit", "offset", "description_format", "title", "location"],
    )
    def test_soporta_los_parametros_del_curl_de_ejemplo(self, name):
        assert name in SUPPORTED_PARAMS

    def test_parametro_desconocido_se_ignora_y_no_rompe(self, workdir):
        """Un typo no debe provocar un 400 que bote la busqueda completa."""
        params = source(titulo="mal escrito", title="bien").build_params()
        assert "titulo" not in params
        assert params["title"] == "bien"
        assert "parametro desconocido 'titulo'" in (workdir / "log.txt").read_text(encoding="utf-8")

    @pytest.mark.parametrize("valor", ["1h", "24h", "7d", "6m"])
    def test_ventanas_de_tiempo_validas(self, valor):
        assert source(time_frame=valor).build_params()["time_frame"] == valor

    @pytest.mark.parametrize("valor", ["3d", "48h", "semana", "7 dias"])
    def test_ventana_invalida_da_error_claro(self, valor):
        with pytest.raises(ProviderError, match="time_frame"):
            source(time_frame=valor).build_params()

    @pytest.mark.parametrize("valor", ["", None])
    def test_ventana_vacia_cae_al_default(self, valor):
        assert source(time_frame=valor).build_params()["time_frame"] == "24h"

    def test_description_format_vacio_se_fuerza_a_text(self):
        """Sin descripcion la AI no tendria nada que evaluar."""
        assert source(description_format="").build_params()["description_format"] == "text"

    @pytest.mark.parametrize(
        "pedido,esperado",
        # La API acepta hasta 1000 por request (V4), no 100.
        [(25, 25), (1, 1), (100, 100), (1000, 1000), (5000, 1000),
         (0, 25), (-5, 25), ("abc", 25), (None, 25)],
    )
    def test_limit_se_acota_al_rango_de_la_api(self, pedido, esperado):
        assert source(limit=pedido).build_params()["limit"] == esperado

    @pytest.mark.parametrize("name", ["has_no_location", "id", "linkedin_id", "cursor"])
    def test_parametros_v4_soportados(self, name):
        assert name in SUPPORTED_PARAMS

    @pytest.mark.parametrize("pedido,esperado", [(0, 0), (50, 50), (-1, 0), ("x", 0), (None, 0)],)
    def test_offset_se_normaliza(self, pedido, esperado):
        assert source(offset=pedido).build_params()["offset"] == esperado


class TestMapeoRespuestaReal:
    def test_mapea_todos_los_trabajos(self, api_jobs):
        result = map_items(_extract_items(api_jobs), to_posting, "fantastic_linkedin")
        assert result.received == len(api_jobs)
        assert result.skipped == 0
        assert len(result.postings) == len(api_jobs)

    def test_campos_clave_poblados(self, api_jobs):
        for raw in api_jobs:
            job = to_posting(raw)
            assert job.title and job.company
            assert job.url.startswith("http")
            assert job.description
            assert job.location
            assert job.source == "fantastic_linkedin"

    def test_fecha_recortada_a_segundos(self, api_jobs):
        assert len(to_posting(api_jobs[0]).posted_at) == 19

    def test_conserva_el_json_crudo(self, api_jobs):
        assert to_posting(api_jobs[0]).raw is api_jobs[0]


class TestMapeoTolerante:
    """La API en vivo y los ejemplos de la doc usan nombres distintos."""

    def test_acepta_el_naming_de_la_documentacion(self):
        raw = {
            "title": "Data Engineer",
            "organization": "ICP Search",
            "url": "https://uk.linkedin.com/jobs/view/x",
            "locations_raw": [{"address": {"addressLocality": "United Kingdom"}}],
            "salary_raw": {"currency": "USD",
                           "value": {"minValue": 100000, "maxValue": 120000, "unitText": "YEAR"}},
            "description_text": "texto",
            "date_posted": "2025-10-13T13:34:45.7",
        }
        job = to_posting(raw)
        assert job.company == "ICP Search"
        assert job.location == "United Kingdom"
        assert job.salary == "USD 100000 - 120000 YEAR"
        assert job.posted_at == "2025-10-13T13:34:45"

    def test_acepta_el_naming_en_vivo(self, api_jobs):
        job = to_posting(api_jobs[0])
        assert job.location  # viene de locations_derived / locations

    def test_sin_descripcion_arma_una_con_los_campos_ai(self, api_jobs):
        raw = dict(api_jobs[0])
        raw.pop("description_text", None)
        job = to_posting(raw)
        assert job.description
        assert "Responsabilidades" in job.description or "Requisitos" in job.description

    def test_ubicacion_cae_a_modalidad_si_no_hay_lugar(self):
        job = to_posting({"title": "T", "organization": "C", "ai_work_arrangement": "Remote Solely"})
        assert job.location == "Remote Solely"


class TestDatosMalos:
    """La regla del proyecto: saltar el item malo y seguir con el resto."""

    @pytest.mark.parametrize(
        "raw", [{}, {"title": "sin empresa"}, {"organization": "sin titulo"},
                {"title": "", "organization": ""}]
    )
    def test_sin_titulo_o_empresa_devuelve_none(self, raw):
        assert to_posting(raw) is None

    def test_un_item_malo_no_bota_la_busqueda(self, api_jobs):
        basura = [None, "texto", 42, {}, {"title": "sin empresa"}] + api_jobs
        result = map_items(_extract_items(basura), to_posting, "fantastic_linkedin")
        assert len(result.postings) == len(api_jobs)
        assert result.skipped == 5
        assert result.received == 5 + len(api_jobs)

    def test_tipos_raros_se_normalizan(self):
        job = to_posting({"title": 12345, "organization": {"name": "Gamma"}})
        assert job.title == "12345"
        assert job.company == "Gamma"

    def test_un_mapper_que_revienta_no_propaga(self, api_jobs):
        def mapper_roto(raw):
            raise ValueError("boom")

        result = map_items(api_jobs, mapper_roto, "test")
        assert result.postings == []
        assert result.skipped == len(api_jobs)

    def test_avisos_acotados_para_no_llenar_memoria(self):
        result = map_items([{}] * 200, to_posting, "test")
        assert result.skipped == 200
        assert len(result.warnings) <= 25


class TestExtractItems:
    def test_lista_directa(self, api_jobs):
        assert len(_extract_items(api_jobs)) == len(api_jobs)

    @pytest.mark.parametrize("key", ["jobs", "data", "results", "items"])
    def test_respuesta_envuelta_en_objeto(self, key, api_jobs):
        assert len(_extract_items({key: api_jobs})) == len(api_jobs)

    @pytest.mark.parametrize("payload", [None, "texto", 42, {}, []])
    def test_formas_inesperadas_devuelven_lista_vacia(self, payload):
        assert _extract_items(payload) == []

    def test_error_de_la_api_se_convierte_en_provider_error(self):
        with pytest.raises(ProviderError, match="not subscribed"):
            _extract_items({"message": "You are not subscribed to this API."})


class TestProveedorLegacy:
    def test_mapea_el_formato_antiguo(self):
        job = legacy_to_posting({
            "title": "Contador", "companyName": "Delta",
            "jobDescription": "desc", "jobPostingUrl": "http://u",
        })
        assert job.company == "Delta"
        assert job.source == "linkedin_data_scraper"

    def test_sin_empresa_devuelve_none(self):
        assert legacy_to_posting({"title": "solo titulo"}) is None

    def test_desenvuelve_response_jobs(self):
        from providers.linkedin_data_scraper import _extract_items as legacy_extract

        assert legacy_extract({"response": {"jobs": [{"a": 1}]}}) == [{"a": 1}]


class TestFetchResult:
    def test_resumen_legible(self):
        result = FetchResult(postings=[JobPosting(title="T", company="C")], received=5, skipped=4)
        assert "1 trabajos utiles de 5 recibidos" in result.summary()
