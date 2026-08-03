"""Los accesores tolerantes: nunca deben lanzar, pase lo que pase."""

import pytest

from utils.safe import as_bool, as_int, as_list, as_text, clean_text, dig, first_present


class TestDig:
    def test_navega_dicts_y_listas(self):
        data = {"a": {"b": [{"c": 1}]}}
        assert dig(data, "a", "b", 0, "c") == 1

    @pytest.mark.parametrize(
        "path",
        [("a", "no_existe"), ("a", "b", 9, "c"), ("x",), ("a", "b", "c"), (0,)],
    )
    def test_ruta_invalida_devuelve_default(self, path):
        data = {"a": {"b": [{"c": 1}]}}
        assert dig(data, *path, default="vacio") == "vacio"

    @pytest.mark.parametrize("data", [None, "texto", 5, [], {}])
    def test_cualquier_entrada_no_lanza(self, data):
        assert dig(data, "a", "b", default=None) is None


class TestFirstPresent:
    def test_toma_la_primera_clave_no_vacia(self):
        data = {"a": "", "b": None, "c": [], "d": "valor"}
        assert first_present(data, ["a", "b", "c", "d"]) == "valor"

    def test_soporta_rutas_anidadas(self):
        data = {"salary": {"currency": "CLP"}}
        assert first_present(data, ["moneda", ["salary", "currency"]]) == "CLP"

    def test_sin_coincidencias_default(self):
        assert first_present({}, ["a", "b"], default="nada") == "nada"


class TestAsText:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("  hola  ", "hola"),
            (["a", "b"], "a, b"),
            ({"name": "ACME"}, "ACME"),
            ({"title": "T"}, "T"),
            (123, "123"),
            (True, "true"),
            (None, ""),
            ([], ""),
            ({}, ""),
            ([None, "x", ""], "x"),
        ],
    )
    def test_convierte_cualquier_cosa(self, value, expected):
        assert as_text(value) == expected


class TestOtros:
    @pytest.mark.parametrize("value,expected", [(None, []), ("a", ["a"]), (["a"], ["a"]), ((1, 2), [1, 2])])
    def test_as_list(self, value, expected):
        assert as_list(value) == expected

    @pytest.mark.parametrize("value,expected", [("5", 5), (5, 5), ("x", None), (None, None), (True, None)])
    def test_as_int(self, value, expected):
        assert as_int(value) == expected

    @pytest.mark.parametrize(
        "value,expected",
        [("true", True), ("si", True), ("0", False), ("no", False), (True, True), ("???", None)],
    )
    def test_as_bool(self, value, expected):
        assert as_bool(value) == expected

    def test_clean_text_corta_y_marca(self):
        assert clean_text("a" * 50, 10) == "a" * 10 + "..."

    def test_clean_text_respeta_texto_corto(self):
        assert clean_text("hola", 10) == "hola"
