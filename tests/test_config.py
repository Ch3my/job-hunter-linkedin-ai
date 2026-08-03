"""Carga de config.json: defaults, retrocompatibilidad y prompt.txt."""

import json

from config import load_config, provider_settings, read_prompt_file, save_config

PERFIL = "Soy contador. Habilidades: auditoría, análisis financiero, asesoría fiscal."


class TestLoadConfig:
    def test_sin_archivo_usa_defaults(self):
        config = load_config()
        assert config["provider"] == "fantastic_linkedin"
        assert config["providers"]["fantastic_linkedin"]["search"]["time_frame"] == "24h"

    def test_json_corrupto_no_lanza(self, workdir):
        (workdir / "config.json").write_text("{ esto no es json", encoding="utf-8")
        assert load_config()["provider"] == "fantastic_linkedin"

    def test_mezcla_profunda_conserva_defaults(self, write_config):
        write_config({"providers": {"fantastic_linkedin": {"search": {"title": "Chef"}}}})
        search = provider_settings("fantastic_linkedin")["search"]
        assert search["title"] == "Chef"
        assert search["time_frame"] == "24h"       # default conservado
        assert search["description_format"] == "text"

    def test_config_plano_antiguo_sigue_funcionando(self, write_config):
        """Un config.json de la version anterior no debe romper la app."""
        write_config({"rapidApiKey": "k", "jobQuery": "contador", "searchLocationId": "104621616"})
        legacy = provider_settings("linkedin_data_scraper")
        assert legacy["jobQuery"] == "contador"
        assert legacy["searchLocationId"] == "104621616"

    def test_la_api_key_llega_a_cada_proveedor(self, write_config):
        write_config({"rapidApiKey": "mi-clave"})
        for name in ("fantastic_linkedin", "linkedin_data_scraper"):
            assert provider_settings(name)["apiKey"] == "mi-clave"

    def test_save_y_load_ida_y_vuelta(self):
        assert save_config({"provider": "linkedin_data_scraper", "rapidApiKey": "abc"})
        config = load_config()
        assert config["provider"] == "linkedin_data_scraper"
        assert config["rapidApiKey"] == "abc"


class TestReadPromptFile:
    def test_sin_archivo_devuelve_vacio(self):
        assert read_prompt_file() == ""

    def test_utf8_con_acentos(self, workdir):
        (workdir / "prompt.txt").write_text(PERFIL, encoding="utf-8")
        assert "auditoría" in read_prompt_file()

    def test_ansi_cp1252_del_bloc_de_notas(self, workdir):
        """El Bloc de notas antiguo guarda en ANSI; no debe perderse el perfil."""
        (workdir / "prompt.txt").write_text(PERFIL, encoding="cp1252")
        assert "auditoría" in read_prompt_file()

    def test_utf8_con_bom(self, workdir):
        (workdir / "prompt.txt").write_text(PERFIL, encoding="utf-8-sig")
        assert read_prompt_file().startswith("Soy contador")
