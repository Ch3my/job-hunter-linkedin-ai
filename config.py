"""Carga y guardado de `config.json`.

El archivo tiene dos niveles:

    {
      "provider": "<nombre del proveedor activo>",
      "rapidApiKey": "...",
      "providers": {
         "<nombre>": { ...opciones propias de ese proveedor... }
      }
    }

`provider_settings()` es lo unico que necesita conocer un proveedor: recibe su
propio bloque, ya mezclado con los defaults y con la API key incluida.
"""

import copy
import json
import os
from typing import Any, Dict

CONFIG_FILE = "config.json"

DEFAULT_PROVIDER = "fantastic_linkedin"

DEFAULT_CONFIG: Dict[str, Any] = {
    "provider": DEFAULT_PROVIDER,
    "rapidApiKey": "",
    "requestTimeout": 30,
    "maxRetries": 3,
    # El corte lo pone el usuario, no el modelo: el LLM entrega un puntaje de
    # 0 a 100 y aca se decide desde donde vale la pena revisar el trabajo.
    # Subirlo filtra mas; bajarlo deja pasar mas.
    "ai": {"minScore": 60},
    "providers": {
        # https://rapidapi.com/fantastic-jobs-fantastic-jobs-default/api/linkedin-job-search-api
        # Las claves de "search" son los nombres reales de los parametros de la
        # API, asi la documentacion sirve directo como referencia.
        "fantastic_linkedin": {
            "search": {
                "time_frame": "24h",
                "limit": 25,
                "offset": 0,
                "description_format": "text",
                "title": "Contador Auditor",
                "location": "Chile",
            }
        },
        # Proveedor anterior, se deja para poder volver atras cambiando "provider".
        # https://rapidapi.com/mgujjargamingm/api/linkedin-data-scraper
        "linkedin_data_scraper": {
            "jobQuery": "Contador Auditor",
            "jobLocation": "chile",
            "searchLocationId": "104621616",
            "workplaceType": "2",
            "sortBy": "DD",
            "jobType": "F",
            "page": "1",
            "easyApply": "false",
        },
    },
}

# Claves planas del config.json antiguo que hay que reubicar dentro de
# providers.linkedin_data_scraper para no romper instalaciones existentes.
LEGACY_KEYS = (
    "jobQuery",
    "jobLocation",
    "searchLocationId",
    "workplaceType",
    "sortBy",
    "jobType",
)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> Dict[str, Any]:
    """Lee config.json y lo mezcla con los defaults. Nunca lanza excepcion."""
    raw: Dict[str, Any] = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                raw = loaded
        except (json.JSONDecodeError, OSError):
            # Config corrupto o ilegible: seguimos con los defaults.
            raw = {}

    config = _deep_merge(DEFAULT_CONFIG, raw)

    # Compatibilidad con el config plano anterior.
    legacy = {key: raw[key] for key in LEGACY_KEYS if key in raw}
    if legacy:
        config["providers"]["linkedin_data_scraper"] = _deep_merge(
            config["providers"]["linkedin_data_scraper"], legacy
        )

    return config


def save_config(config: Dict[str, Any]) -> bool:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


def active_provider_name(config: Dict[str, Any] = None) -> str:
    config = config or load_config()
    name = config.get("provider") or DEFAULT_PROVIDER
    return str(name).strip()


def provider_settings(name: str, config: Dict[str, Any] = None) -> Dict[str, Any]:
    """Devuelve el bloque de configuracion de un proveedor.

    Incluye tambien las claves compartidas (apiKey, timeout, reintentos) para
    que el proveedor reciba todo lo que necesita en un solo diccionario.
    """
    config = config or load_config()
    providers = config.get("providers") or {}
    settings = copy.deepcopy(providers.get(name) or {})
    settings.setdefault("apiKey", config.get("rapidApiKey", ""))
    settings.setdefault("requestTimeout", config.get("requestTimeout", 30))
    settings.setdefault("maxRetries", config.get("maxRetries", 3))
    return settings


def min_score(config: Dict[str, Any] = None) -> int:
    """Puntaje minimo (0-100) para considerar relevante un trabajo.

    Un valor fuera de rango o no numerico se ignora y se usa el default: el
    config lo edita una persona a mano y un typo no puede dejar la busqueda
    filtrando todo (100) o nada (0) sin aviso.
    """
    config = config or load_config()
    default = DEFAULT_CONFIG["ai"]["minScore"]
    valor = (config.get("ai") or {}).get("minScore", default)
    try:
        valor = int(valor)
    except (TypeError, ValueError):
        return default
    return valor if 0 <= valor <= 100 else default


def read_prompt_file(filename: str = "prompt.txt") -> str:
    """Lee el perfil del usuario (prompt.txt). Devuelve "" si no se puede leer.

    Se prueban varias codificaciones porque el archivo lo escribe una persona
    con el editor que tenga a mano: el Bloc de notas antiguo guarda en ANSI
    (cp1252) y ahi los acentos de "auditoría" o "análisis" no son UTF-8 valido.
    Antes eso se leia con la codificacion del sistema; hay que seguir
    aceptandolo o un prompt.txt existente dejaria de aplicarse.
    """
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(filename, "r", encoding=encoding) as handle:
                return handle.read()
        except UnicodeDecodeError:
            continue  # probamos la siguiente codificacion
        except OSError:
            return ""  # no existe o no se puede abrir: no tiene sentido reintentar
    return ""
