"""Adapter: LinkedIn Job Search API (Fantastic Jobs) en RapidAPI.

https://rapidapi.com/fantastic-jobs-fantastic-jobs-default/api/linkedin-job-search-api

    GET https://linkedin-job-search-api.p.rapidapi.com/active-jb
        ?time_frame=24h&limit=10&description_format=text&title=...&location=...

La respuesta es una lista de objetos JSON.

Nota sobre los nombres de campo: la respuesta en vivo usa `locations`, `salary`,
`direct_apply`, `org_linkedin_*`, mientras que los ejemplos de la documentacion
usan `locations_raw`, `salary_raw`, `directapply`, `linkedin_org_*`. El mapeo
acepta las dos variantes, asi que la app no se rompe segun cual devuelva la API.

Dos partes bien separadas:
  - `to_posting()`: funcion pura, JSON crudo -> JobPosting. Testeable sin red.
  - `FantasticLinkedInSource`: arma los parametros y llama al cliente HTTP.
"""

from typing import Any, Dict, List, Optional

from models import JobPosting
from providers.base import FetchResult, ProviderError, map_items
from providers.http import rapidapi_client
from utils import append_to_log
from utils.safe import as_bool, as_int, as_list, as_text, clean_text, dig, first_present

NAME = "fantastic_linkedin"
HOST = "linkedin-job-search-api.p.rapidapi.com"
ENDPOINT = "active-jb"

VALID_TIME_FRAMES = ("1h", "24h", "7d", "6m")

MAX_DESCRIPTION_CHARS = 20000

# Parametros que acepta el endpoint. Se usan los nombres tal cual los publica la
# API: asi la pagina de documentacion sirve directamente como referencia del
# config.json, sin una tabla de traduccion que se desactualice.
SUPPORTED_PARAMS = frozenset({
    "time_frame", "limit", "offset", "cursor", "description_format",
    "title", "title_advanced",
    "description", "description_advanced",
    "location", "location_advanced", "has_no_location",
    "organization", "organization_advanced", "exclude_organization",
    "organization_slug", "exclude_organization_slug",
    "organization_industry", "exclude_organization_industry",
    "organization_headcount_gte", "organization_headcount_lt",
    "organization_agency",
    "date_posted_gte", "date_posted_lt", "date_created_gte", "date_created_lt",
    "seniority", "direct_apply", "has_salary", "exclude_ats_duplicate",
    "ai_experience_level", "ai_work_arrangement", "ai_employment_type",
    "ai_education", "ai_visa_sponsorship",
    "ai_taxonomies_a", "exclude_ai_taxonomies_a", "ai_taxonomies_a_primary",
    "id", "linkedin_id",
})

# La API acepta hasta 1000 por request (su default es 100).
#
# El plan cobra dos creditos distintos y conviene entenderlos antes de tocar
# `limit`: cada llamada descuenta 1 credito de "requests", y cada trabajo
# devuelto descuenta 1 de "jobs". En el plan BASIC son 25 requests y 250 jobs
# al mes, o sea 10 trabajos por llamada para que ambos se acaben juntos.
# Subir `limit` NO gasta requests extra: trae mas trabajos por la misma llamada.
MIN_LIMIT = 1
MAX_LIMIT = 1000

DEFAULT_PARAMS: Dict[str, Any] = {
    "time_frame": "24h",
    "limit": 25,
    "offset": 0,
    # Sin esto la API NO incluye el campo de descripcion (lo omite para ahorrar
    # payload) y la AI se quedaria sin texto que evaluar.
    "description_format": "text",
}


# --------------------------------------------------------------------------
# Mapeo: JSON crudo -> JobPosting  (funcion pura, sin red)
# --------------------------------------------------------------------------

def _location(raw: Dict[str, Any]) -> str:
    """Ubicacion legible, probando los varios campos que puede traer la API."""
    derived = first_present(
        raw, ["locations_derived", "cities_derived", "regions_derived", "countries_derived"]
    )
    text = as_text(derived)
    if text:
        return text

    # Fallback: formato schema.org (`locations` en vivo, `locations_raw` en los docs).
    places = as_list(first_present(raw, ["locations", "locations_raw"]))
    if places:
        address = dig(places[0], "address", default={})
        parts = [
            as_text(dig(address, "addressLocality")),
            as_text(dig(address, "addressRegion")),
            as_text(dig(address, "addressCountry")),
        ]
        joined = ", ".join(part for part in parts if part)
        if joined:
            return joined

    arrangement = as_text(raw.get("ai_work_arrangement"))
    if arrangement:
        return arrangement
    if as_bool(raw.get("remote_derived")):
        return "Remoto"
    return as_text(raw.get("location_type"))


def _salary(raw: Dict[str, Any]) -> str:
    """La renta viene estructurada (schema.org), enriquecida por AI, o no viene."""
    currency = as_text(first_present(
        raw, ["ai_salary_currency", ["salary", "currency"], ["salary_raw", "currency"]]))
    minimum = first_present(raw, [
        "ai_salary_min_value", "ai_salary_minvalue",
        ["salary", "value", "minValue"], ["salary_raw", "value", "minValue"]])
    maximum = first_present(raw, [
        "ai_salary_max_value", "ai_salary_maxvalue",
        ["salary", "value", "maxValue"], ["salary_raw", "value", "maxValue"]])
    unit = as_text(first_present(raw, [
        "ai_salary_unit_text", "ai_salary_unittext",
        ["salary", "value", "unitText"], ["salary_raw", "value", "unitText"]]))

    if minimum or maximum:
        rango = " - ".join(as_text(v) for v in (minimum, maximum) if v not in (None, ""))
        return " ".join(part for part in (currency, rango, unit) if part).strip()

    single = first_present(raw, ["ai_salary_value"])
    if single:
        return " ".join(part for part in (currency, as_text(single), unit) if part).strip()

    return clean_text(first_present(raw, ["salary", "salary_raw"]), 200)


def _description(raw: Dict[str, Any]) -> str:
    """Texto de la oferta.

    `description_text` solo viene si se pidio `description_format=text`. Si no
    esta, se arma un resumen con los campos que la API enriquece con AI: para
    clasificar relevancia sirven casi tan bien como la descripcion completa.
    """
    text = as_text(first_present(raw, ["description_text", "description", "description_html"]))
    if text:
        return clean_text(text, MAX_DESCRIPTION_CHARS)

    bloques = [
        ("Responsabilidades", as_text(raw.get("ai_core_responsibilities"))),
        ("Requisitos", as_text(raw.get("ai_requirements_summary"))),
        ("Habilidades", as_text(raw.get("ai_key_skills"))),
        ("Educacion", as_text(raw.get("ai_education"))),
        ("Beneficios", as_text(raw.get("ai_benefits"))),
    ]
    armado = "\n\n".join(f"{titulo}:\n{valor}" for titulo, valor in bloques if valor)
    return clean_text(armado, MAX_DESCRIPTION_CHARS)


def to_posting(raw: Dict[str, Any]) -> Optional[JobPosting]:
    """Convierte un item de la API en JobPosting.

    Devuelve None si falta titulo o empresa, que son la clave primaria en la
    base de datos. Cualquier otro campo ausente simplemente queda vacio.
    """
    title = as_text(first_present(raw, ["title", "job_title"]))
    company = as_text(first_present(raw, ["organization", "organization_name", "company"]))

    if not title or not company:
        return None

    return JobPosting(
        title=title,
        company=company,
        url=as_text(first_present(raw, ["url", "external_apply_url", "organization_url"])),
        description=_description(raw),
        location=_location(raw),
        employment_type=as_text(first_present(raw, ["employment_type", "ai_employment_type"])),
        seniority=as_text(first_present(raw, ["seniority", "ai_experience_level"])),
        salary=_salary(raw),
        posted_at=as_text(first_present(raw, ["date_posted", "date_created"]))[:19],
        external_id=as_text(first_present(raw, ["id", "linkedin_id"])),
        source=NAME,
        raw=raw,
    )


# --------------------------------------------------------------------------
# Transporte: arma los parametros y consulta la API
# --------------------------------------------------------------------------

class FantasticLinkedInSource:
    """Cumple el protocolo `JobSource` sin heredar de nada."""

    name = NAME

    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings or {}
        self.client = rapidapi_client(HOST, self.settings)

    def build_params(self) -> Dict[str, Any]:
        """Traduce el bloque `search` de config.json a los parametros del endpoint.

        Las claves de config.json son los nombres reales de la API, asi que se
        pasan tal cual. Las desconocidas se descartan con un aviso en el log: un
        typo no deberia provocar un 400 que bote la busqueda completa.
        """
        params: Dict[str, Any] = dict(DEFAULT_PARAMS)
        search = self.settings.get("search")

        if not isinstance(search, dict):
            search = {}
            append_to_log(f"[{NAME}] config.json no tiene un bloque 'search', se usan los defaults")

        for key, value in search.items():
            if key in SUPPORTED_PARAMS:
                params[key] = value
            else:
                append_to_log(f"[{NAME}] parametro desconocido '{key}' en config.json, se ignora")

        # Vacio significa "usa el default", igual que el resto de las opciones.
        time_frame = as_text(params.get("time_frame"), DEFAULT_PARAMS["time_frame"])
        if time_frame not in VALID_TIME_FRAMES:
            raise ProviderError(
                f"time_frame '{time_frame}' no valido. Opciones: {', '.join(VALID_TIME_FRAMES)}"
            )
        params["time_frame"] = time_frame

        # Un valor ausente, no numerico o fuera de rango cae al default en vez
        # de mandar algo que la API rechazaria.
        limit = as_int(params.get("limit"))
        if limit is None or limit < MIN_LIMIT:
            limit = DEFAULT_PARAMS["limit"]
        params["limit"] = min(limit, MAX_LIMIT)

        offset = as_int(params.get("offset"))
        params["offset"] = offset if offset and offset > 0 else 0

        # Sin descripcion la AI no puede evaluar nada, asi que no se permite vacio.
        if not as_text(params.get("description_format")):
            params["description_format"] = "text"

        return params

    def fetch(self) -> FetchResult:
        payload = self.client.get_json(ENDPOINT, self.build_params())
        result = map_items(_extract_items(payload), to_posting, NAME)

        # Cada trabajo devuelto descuenta un credito, asi que conviene saber
        # cuanto queda antes de toparse con un 429.
        resumen = self.client.quota_summary()
        if resumen:
            result.quota = resumen
            append_to_log(f"[{NAME}] {resumen}")

        return result


def _extract_items(payload: Any) -> List[Any]:
    """Saca la lista de trabajos del payload.

    Normalmente la API devuelve una lista directa, pero si algun dia la envuelve
    en un objeto (o devuelve un error con forma de dict), esto lo resuelve sin
    romper.
    """
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for key in ("jobs", "data", "results", "items", "response"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = value.get("jobs") or value.get("data")
                if isinstance(nested, list):
                    return nested

        message = as_text(first_present(payload, ["message", "error", "detail", "title"]))
        if message:
            raise ProviderError(f"La API respondio con un error: {message}")

    return []


def build(settings: Dict[str, Any]) -> FantasticLinkedInSource:
    return FantasticLinkedInSource(settings)
