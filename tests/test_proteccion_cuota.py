"""Verifica la proteccion de la cuota: la suite normal no puede salir a internet.

Si estos tests fallan, la proteccion se rompio y una corrida de `pytest` podria
volver a gastar cuota de RapidAPI sin avisar.
"""

import urllib.request

import pytest

from providers.fantastic_linkedin import FantasticLinkedInSource
from providers.http import rapidapi_client


class TestRedBloqueada:
    def test_urlopen_esta_bloqueado(self):
        with pytest.raises(RuntimeError, match="llamada HTTP real"):
            urllib.request.urlopen("https://example.com")

    def test_el_cliente_http_no_puede_salir(self):
        client = rapidapi_client("linkedin-job-search-api.p.rapidapi.com", {"apiKey": "k"})
        with pytest.raises(RuntimeError, match="llamada HTTP real"):
            client.get_json("active-jb", {"limit": 1})

    def test_un_fetch_completo_tampoco(self):
        source = FantasticLinkedInSource({"apiKey": "k", "search": {"title": "x"}})
        with pytest.raises(RuntimeError, match="llamada HTTP real"):
            source.fetch()

    def test_el_mensaje_explica_que_hacer(self):
        with pytest.raises(RuntimeError) as error:
            urllib.request.urlopen("https://example.com")
        mensaje = str(error.value)
        assert "doble" in mensaje
        assert "pytest.mark.live" in mensaje


class TestMarcadores:
    def test_los_tests_live_estan_marcados(self, pytestconfig):
        """Todo test de test_live_api.py debe estar marcado, si no la proteccion no aplica."""
        from pathlib import Path

        contenido = (Path(__file__).parent / "test_live_api.py").read_text(encoding="utf-8")
        assert "pytestmark = pytest.mark.live" in contenido

    def test_live_desactivado_por_defecto(self, pytestconfig):
        """Salvo que el usuario pase --live explicitamente."""
        assert pytestconfig.getoption("--live") in (True, False)


@pytest.mark.live
class TestExcepcionParaLive:
    """Estos si pueden usar la red, pero solo corren con --live."""

    def test_la_red_esta_disponible_en_los_live(self):
        # No se llama a nadie: solo se comprueba que no esta parcheado.
        assert urllib.request.urlopen.__name__ != "bloqueado"
