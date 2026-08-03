"""Accesores tolerantes a fallas para payloads de APIs externas.

La regla del proyecto: si un campo no existe, o viene con un tipo distinto al
esperado, no se lanza una excepcion. Se devuelve el default y se sigue.
"""

from typing import Any, Iterable, List, Optional


def dig(data: Any, *path: Any, default: Any = None) -> Any:
    """Navega dicts/listas anidados sin reventar.

    dig(job, "organization", "name")     -> job["organization"]["name"]
    dig(job, "locations_raw", 0, "name") -> job["locations_raw"][0]["name"]
    """
    current = data
    for key in path:
        if current is None:
            return default
        try:
            if isinstance(key, int):
                if not isinstance(current, (list, tuple)) or len(current) <= key:
                    return default
                current = current[key]
            else:
                if not isinstance(current, dict) or key not in current:
                    return default
                current = current[key]
        except Exception:
            return default
    return default if current is None else current


def first_present(data: Any, keys: Iterable[Any], default: Any = None) -> Any:
    """Devuelve el primer campo no vacio entre varias claves candidatas.

    Util cuando la API renombra campos entre versiones: pasamos los dos nombres
    y seguimos funcionando con cualquiera de los dos.
    """
    for key in keys:
        path = key if isinstance(key, (list, tuple)) else (key,)
        value = dig(data, *path)
        if value not in (None, "", [], {}):
            return value
    return default


def as_text(value: Any, default: str = "") -> str:
    """Convierte cualquier cosa a un string limpio.

    Listas -> se unen con coma. Dicts -> se busca una clave tipica de nombre.
    """
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip() or default
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        parts = [as_text(item) for item in value]
        joined = ", ".join(part for part in parts if part)
        return joined or default
    if isinstance(value, dict):
        for key in ("name", "title", "value", "text", "label"):
            if key in value:
                return as_text(value[key], default)
        return default
    try:
        return str(value).strip() or default
    except Exception:
        return default


def as_list(value: Any) -> List[Any]:
    """Siempre devuelve una lista, aunque venga un escalar o None."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def as_bool(value: Any, default: Optional[bool] = None) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "si", "y"):
            return True
        if lowered in ("false", "0", "no", "n"):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def clean_text(value: Any, max_length: Optional[int] = None) -> str:
    """Normaliza el texto y opcionalmente lo corta."""
    text = as_text(value)
    if not text:
        return ""
    text = text.strip()
    if max_length and len(text) > max_length:
        return text[:max_length].rstrip() + "..."
    return text
