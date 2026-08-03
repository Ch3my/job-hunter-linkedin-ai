"""Fixtures compartidas.

Equivalencias con vitest, por si vienes de ahi:

    vitest                      pytest
    ------------------------    ------------------------------------------
    describe / it               clases o funciones test_*
    expect(x).toBe(y)           assert x == y
    beforeEach                  @pytest.fixture (autouse=True si es global)
    vi.fn() / vi.mock()         monkeypatch, o simplemente una clase falsa
    test.skip / test.only       @pytest.mark.skip / -k "nombre"
    snapshot                    un .json en tests/fixtures/

Como los puertos del proyecto son `Protocol`, un doble de prueba es una clase
normal con los mismos metodos: no hace falta libreria de mocking.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Permite `import config`, `import providers`, ... sin instalar el proyecto.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Proteccion de la cuota de la API
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Ejecuta tambien los tests contra la API real (CONSUME CUOTA de RapidAPI)",
    )


def pytest_collection_modifyitems(config, items):
    """Sin --live, los tests marcados `live` ni siquiera se intentan."""
    if config.getoption("--live"):
        return
    saltar = pytest.mark.skip(reason="necesita --live (consume cuota de RapidAPI)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(saltar)


@pytest.fixture(autouse=True)
def sin_red(request, monkeypatch):
    """Red bloqueada en todo test que no este marcado `live`.

    Es la red de seguridad: si alguien escribe un test nuevo y se olvida de
    usar un doble, el test falla con un mensaje claro en vez de gastar cuota
    sin que nadie se entere.
    """
    if "live" in request.keywords:
        return

    def bloqueado(*args, **kwargs):
        raise RuntimeError(
            "Este test intento hacer una llamada HTTP real. "
            "Usa un doble (ver FakeSource en test_job_hunt.py) o marcalo "
            "con @pytest.mark.live si de verdad necesita la API."
        )

    monkeypatch.setattr(urllib.request, "urlopen", bloqueado)


@pytest.fixture(autouse=True)
def workdir(tmp_path, monkeypatch):
    """Cada test corre en su propia carpeta vacia.

    Es importante: la app escribe jobs.db, log.txt y lee config.json del
    directorio actual. Sin esto los tests pisarian los datos reales.
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def api_jobs():
    """Respuesta real de GET /active-jb (3 trabajos), guardada como fixture."""
    with open(FIXTURES / "active_jb_sample.json", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def write_config(workdir):
    """Escribe un config.json en el directorio del test."""

    def _write(data):
        path = workdir / "config.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def api_key():
    """Clave real desde el config.json del proyecto; salta el test si no hay."""
    path = ROOT / "config.json"
    if not path.exists():
        pytest.skip("no hay config.json con rapidApiKey")
    key = json.loads(path.read_text(encoding="utf-8")).get("rapidApiKey", "")
    if not key:
        pytest.skip("config.json no tiene rapidApiKey")
    return key


@pytest.fixture
def sin_cuota():
    """Convierte un 429 (cuota agotada) en skip, no en fallo.

    Quedarse sin requests del plan no es un bug del codigo: si el test fallara,
    la suite en rojo mentiria sobre el estado del proyecto.
    """
    from contextlib import contextmanager

    from providers.base import ProviderError

    @contextmanager
    def _guard():
        try:
            yield
        except ProviderError as error:
            texto = str(error)
            if "429" in texto or "quota" in texto.lower():
                pytest.skip(f"cuota de RapidAPI agotada: {texto[:90]}")
            raise

    return _guard
