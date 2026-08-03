"""Utilidades transversales, sin logica de negocio.

  - `log`:       escritura a log.txt (nunca lanza excepciones)
  - `safe`:      accesores tolerantes a fallas para JSON de APIs externas
  - `resources`: rutas a los assets (funciona igual en fuente y en el .exe)

Se importan desde aca:

    from utils import append_to_log, log_exception, icon_path
    from utils.safe import as_text, dig, first_present
"""

from utils.log import append_to_log, log_exception, log_json, open_log_file, save_to_json
from utils.resources import find_resource, icon_path, resource_path
from utils.safe import as_bool, as_int, as_list, as_text, clean_text, dig, first_present

__all__ = [
    # log
    "append_to_log",
    "log_exception",
    "log_json",
    "open_log_file",
    "save_to_json",
    # resources
    "find_resource",
    "icon_path",
    "resource_path",
    # safe
    "as_bool",
    "as_int",
    "as_list",
    "as_text",
    "clean_text",
    "dig",
    "first_present",
]
