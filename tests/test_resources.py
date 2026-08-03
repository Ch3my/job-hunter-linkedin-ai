"""Assets e icono de la ventana."""

import os
import sys

import pytest

from utils.resources import PROJECT_ROOT, base_path, find_resource, icon_path, resource_path


class TestRutasDeAssets:
    def test_encuentra_el_icono_sin_depender_del_cwd(self, workdir):
        """El test corre en un tmp_path, no en la carpeta del proyecto."""
        assert os.getcwd() != PROJECT_ROOT
        path = icon_path()
        assert path and os.path.isabs(path)
        assert os.path.isfile(path)
        assert path.lower().endswith("favicon.ico")

    def test_asset_inexistente_devuelve_vacio(self):
        assert find_resource("assets", "no_existe.ico") == ""

    def test_modo_pyinstaller_usa_meipass(self, monkeypatch):
        monkeypatch.setattr(sys, "_MEIPASS", os.path.join("C:", "Temp", "_MEI123"), raising=False)
        assert base_path().endswith("_MEI123")
        assert resource_path("assets", "favicon.ico").startswith(base_path())

    def test_modo_normal_usa_la_raiz_del_proyecto(self):
        assert base_path() == PROJECT_ROOT


@pytest.mark.gui
class TestVentana:
    """Abren una ventana Tk real; se saltan si no hay escritorio."""

    @pytest.fixture
    def tk_root(self):
        tk = pytest.importorskip("tkinter")
        try:
            root = tk.Tk()
        except tk.TclError as error:
            pytest.skip(f"sin escritorio disponible: {error}")
        yield root
        root.destroy()

    def test_la_ventana_se_construye_completa(self, tk_root):
        from ui.app import JobDatabaseGUI

        app = JobDatabaseGUI(tk_root)
        tk_root.update()
        assert tk_root.title() == "Job Database Navigator"
        assert app.tree is not None
        assert app.thread_button["text"] == "Hunt!"

    def test_tk_acepta_nuestro_ico(self, tk_root):
        tk_root.iconbitmap(icon_path())   # no debe lanzar

    def test_sin_icono_la_app_arranca_igual(self, tk_root, monkeypatch):
        import ui.app as app_module

        monkeypatch.setattr(app_module, "icon_path", lambda: "")
        app_module.JobDatabaseGUI(tk_root)
        tk_root.update()
        assert tk_root.title() == "Job Database Navigator"

    def test_identidad_de_barra_de_tareas_no_lanza(self):
        from ui.app import _claim_windows_taskbar_identity

        _claim_windows_taskbar_identity()
