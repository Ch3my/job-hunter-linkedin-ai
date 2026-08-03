"""Ubicacion de archivos que acompanan a la aplicacion (assets).

Hay que resolver la ruta en dos escenarios distintos:

  - Ejecutando `python main.py`: los assets estan junto al codigo fuente.
  - Ejecutando el .exe de PyInstaller: se descomprimen en una carpeta temporal
    cuya ruta queda en `sys._MEIPASS`.

Usar rutas relativas sueltas ("assets/favicon.ico") falla en ambos casos si la
app se abre desde otro directorio de trabajo.
"""

import os
import sys

# .../job-hunter-ai/utils/resources.py -> .../job-hunter-ai
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ICON_FILE = os.path.join("assets", "favicon.ico")


def base_path() -> str:
    """Carpeta donde buscar los assets, segun como se este ejecutando."""
    bundled = getattr(sys, "_MEIPASS", None)  # lo define PyInstaller al arrancar
    return bundled if bundled else PROJECT_ROOT


def resource_path(*parts: str) -> str:
    """Ruta absoluta a un asset. No verifica que exista."""
    return os.path.join(base_path(), *parts)


def find_resource(*parts: str) -> str:
    """Ruta absoluta a un asset si existe; "" si no.

    Permite que la app siga funcionando aunque falte el archivo.
    """
    path = resource_path(*parts)
    return path if os.path.isfile(path) else ""


def icon_path() -> str:
    """Ruta al icono de la ventana, o "" si no esta disponible."""
    return find_resource(*ICON_FILE.split(os.sep))
