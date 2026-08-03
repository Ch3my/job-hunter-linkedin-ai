"""Tests contra la API REAL. Consumen cuota, por eso no corren por defecto.

    pytest -m live          solo estos
    pytest                  todo lo demas (estos quedan deseleccionados)

Sirven para detectar que la API cambio: si un dia dejan de pasar mientras el
resto sigue verde, el problema esta del lado del proveedor, no del codigo.
"""

import pytest

from providers.base import map_items
from providers.fantastic_linkedin import (
    ENDPOINT,
    HOST,
    FantasticLinkedInSource,
    _extract_items,
    to_posting,
)
from providers.http import rapidapi_client

pytestmark = pytest.mark.live


@pytest.fixture
def source(api_key):
    return FantasticLinkedInSource({
        "apiKey": api_key,
        "search": {"time_frame": "7d", "limit": 5, "title": "Contador", "location": "Chile"},
    })


class TestEndpointVivo:
    def test_el_endpoint_existe(self, api_key, sin_cuota):
        """Regresion: /active-jb-7d daba 404, la ventana va en time_frame."""
        client = rapidapi_client(HOST, {"apiKey": api_key})
        with sin_cuota():
            payload = client.get_json(ENDPOINT, {"limit": 1, "time_frame": "24h"})
        assert isinstance(payload, list)

    def test_devuelve_trabajos_utilizables(self, source, sin_cuota):
        with sin_cuota():
            result = source.fetch()
        assert result.received > 0, "revisa los filtros title/location"
        assert result.postings
        assert result.skipped == 0

    def test_todos_traen_descripcion(self, source, sin_cuota):
        """Sin description_format=text la AI se quedaria sin texto que evaluar."""
        with sin_cuota():
            postings = source.fetch().postings
        for job in postings:
            assert job.description, f"sin descripcion: {job.title}"

    def test_campos_clave_presentes(self, source, sin_cuota):
        with sin_cuota():
            postings = source.fetch().postings
        for job in postings:
            assert job.title and job.company
            assert job.url.startswith("http")
            assert job.location
            assert job.posted_at

    def test_los_filtros_se_aplican(self, api_key, sin_cuota):
        source = FantasticLinkedInSource({
            "apiKey": api_key,
            "search": {"time_frame": "7d", "limit": 5, "title": "Nutricionista", "location": "Chile"},
        })
        with sin_cuota():
            postings = source.fetch().postings
        titulos = [j.title.lower() for j in postings]
        assert titulos, "sin resultados para el filtro"
        assert any("nutricion" in t for t in titulos)

    def test_la_forma_de_la_respuesta_no_cambio(self, api_key, sin_cuota):
        """Si esto falla, la API cambio sus campos: hay que revisar el mapper."""
        client = rapidapi_client(HOST, {"apiKey": api_key})
        with sin_cuota():
            payload = client.get_json(ENDPOINT, {"limit": 1, "time_frame": "24h",
                                                 "description_format": "text"})
        job = _extract_items(payload)[0]
        for campo in ("id", "title", "organization", "url", "date_posted", "description_text"):
            assert campo in job, f"la API ya no devuelve '{campo}'"

    def test_el_mapper_no_descarta_nada_real(self, api_key, sin_cuota):
        client = rapidapi_client(HOST, {"apiKey": api_key})
        with sin_cuota():
            payload = client.get_json(ENDPOINT, {"limit": 10, "time_frame": "24h",
                                                 "description_format": "text"})
        result = map_items(_extract_items(payload), to_posting, "fantastic_linkedin")
        assert result.skipped == 0, result.warnings


class TestErroresReales:
    """Estos no dependen de la cuota: se validan antes de gastar una request util."""

    def test_clave_invalida_da_mensaje_claro(self):
        from providers.base import ProviderError

        client = rapidapi_client(HOST, {"apiKey": "clave-invalida", "maxRetries": 1})
        with pytest.raises(ProviderError, match="credencial|rechazo"):
            client.get_json(ENDPOINT, {"limit": 1, "time_frame": "24h"})
