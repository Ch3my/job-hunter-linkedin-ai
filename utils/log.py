"""Log a `log.txt` y utilidades de archivos."""

import json
import os
import platform
import subprocess
import traceback
from datetime import datetime
from typing import Any

LOG_FILE = "log.txt"


def append_to_log(text: Any) -> None:
    """Escribe una linea en el log. Nunca propaga errores."""
    try:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as log_file:
            log_file.write(f"{current_time} - {text}\n")
    except Exception:
        # El log es best-effort: si falla, no puede tumbar la aplicacion.
        pass


def log_exception(context: str, error: BaseException) -> None:
    """Registra una excepcion con su traceback, sin volver a lanzarla."""
    detail = "".join(traceback.format_exception_only(type(error), error)).strip()
    append_to_log(f"[ERROR] {context}: {detail}")


def log_json(label: str, payload: Any) -> None:
    try:
        append_to_log(f"{label}: {json.dumps(payload, indent=2, ensure_ascii=False, default=str)}")
    except Exception:
        append_to_log(f"{label}: <no serializable>")


def open_log_file() -> bool:
    if not os.path.exists(LOG_FILE):
        return False
    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.call(("open", LOG_FILE))
        elif system == "Windows":
            os.startfile(LOG_FILE)  # type: ignore[attr-defined]
        else:
            subprocess.call(("xdg-open", LOG_FILE))
        return True
    except Exception:
        return False


def save_to_json(data: Any, filename: str = None) -> str:
    """Guarda un payload a disco (debug). Devuelve el nombre o string vacio."""
    if filename is None:
        filename = f"jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        with open(filename, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=4, default=str)
        return filename
    except Exception as error:
        log_exception("save_to_json", error)
        return ""
