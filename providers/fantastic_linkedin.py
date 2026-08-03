"""Adapter: LinkedIn Job Search API (Fantastic Jobs) en RapidAPI.

https://rapidapi.com/fantastic-jobs-fantastic-jobs-default/api/linkedin-job-search-api

La respuesta es una lista de objetos JSON. Los nombres de campo estan en
snake_case y varios son opcionales segun el plan y los parametros pedidos, asi
que todo el mapeo pasa por los accesores tolerantes de `safe.py`.

Este modulo tiene dos partes bien separadas:
  - `to_posting()`: funcion pura, JSON crudo -> JobPosting. Se puede testear
    con un archivo JSON de ejemplo, sin red.
  - `FantasticLinkedInSource`: arma los parametros y llama al cliente HTTP.
"""

from typing import Any, Dict, List, Optional

from models import JobPosting
from providers.base import FetchResult, ProviderError, map_items
from providers.http import rapidapi_client
from utils.safe import as_bool, as_int, as_text, clean_text, dig, first_present

NAME = "fantastic_linkedin"
HOST = "linkedin-job-search-api.p.rapidapi.com"

# Ventanas de tiempo que expone la API. La 7d es la del playground.
VALID_ENDPOINTS = ("active-jb-1h", "active-jb-24h", "active-jb-7d")
DEFAULT_ENDPOINT = "active-jb-7d"

MAX_DESCRIPTION_CHARS = 20000


# --------------------------------------------------------------------------
# Mapeo: JSON crudo -> JobPosting  (funcion pura, sin red)
# --------------------------------------------------------------------------

def _location(raw: Dict[str, Any]) -> str:
    """Arma la ubicacion probando los varios campos que puede traer la API."""
    derived = first_present(raw, ["locations_derived", "cities_derived", "regions_derived", "countries_derived"])
    if derived:
        text = as_text(derived)
        if text:
            return text

    # Fallback: locations_raw viene en formato schema.org (Place -> address).
    address = dig(raw, "locations_raw", 0, "address", default={})
    parts = [
        as_text(dig(address, "addressLocality")),
        as_text(dig(address, "addressRegion")),
        as_text(dig(address, "addressCountry")),
    ]
    joined = ", ".join(part for part in parts if part)
    if joined:
        return joined

    if as_bool(raw.get("remote_derived")):
        return "Remoto"

    return as_text(raw.get("location_type"))


def _salary(raw: Dict[str, Any]) -> str:
    """La renta puede venir estructurada (schema.org), como texto, o enriquecida por AI."""
    currency = as_text(first_present(raw, ["ai_salary_currency", ["salary_raw", "currency"]]))
    minimum = first_present(raw, ["ai_salary_minvalue", "ai_salary_min_value", ["salary_raw", "value", "minValue"]])
    maximum = first_present(raw, ["ai_salary_maxvalue", "ai_salary_max_value", ["salary_raw", "value", "maxValue"]])
    unit = as_text(first_present(raw, ["ai_salary_unittext", "ai_salary_unit_text", ["salary_raw", "value", "unitText"]]))

    if minimum or maximum:
        rango = " - ".join(as_text(value) for value in (minimum, maximum) if value not in (None, ""))
        return " ".join(part for part in (currency, rango, unit) if part).strip()

    return clean_text(raw.get("salary_raw"), 200)


def to_posting(raw: Dict[str, Any]) -> Optional[JobPosting]:
    """Convierte un item de la API en JobPosting.

    Devuelve None si falta titulo o empresa, que son la clave primaria en la
    base de datos. Cualquier otro campo ausente simplemente queda vacio.
    """
    title = as_text(first_present(raw, ["title", "job_title", "name"]))
    company = as_text(first_present(raw, ["organization", "company", "organization_name", "employer"]))

    if not title or not company:
        return None

    description = as_text(first_present(raw, ["description_text", "description", "descriptionHtml", "description_html"]))

    return JobPosting(
        title=title,
        company=company,
        url=as_text(first_present(raw, ["url", "external_apply_url", "job_url", "organization_url"])),
        description=clean_text(description, MAX_DESCRIPTION_CHARS),
        location=_location(raw),
        employment_type=as_text(first_present(raw, ["employment_type", "ai_employment_type"])),
        seniority=as_text(first_present(raw, ["seniority", "ai_experience_level"])),
        salary=_salary(raw),
        posted_at=as_text(first_present(raw, ["date_posted", "date_created", "datePosted"]))[:19],
        external_id=as_text(first_present(raw, ["id", "job_id", "_id"])),
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

    def _endpoint(self) -> str:
        endpoint = as_text(self.settings.get("endpoint"), DEFAULT_ENDPOINT).strip("/")
        if endpoint not in VALID_ENDPOINTS:
            raise ProviderError(
                f"Endpoint '{endpoint}' no valido. Opciones: {', '.join(VALID_ENDPOINTS)}"
            )
        return endpoint

    def build_params(self) -> Dict[str, Any]:
        """Traduce config.json a los parametros de la API.

        Los valores vacios o None se descartan en el cliente HTTP, asi que
        dejar una opcion en blanco equivale a no filtrar por ella.
        """
        settings = self.settings
        limit = as_int(settings.get("limit"), 25) or 25

        return {
            "limit": max(1, min(limit, 100)),
            "offset": as_int(settings.get("offset"), 0) or 0,
            "title_filter": as_text(settings.get("titleFilter")),
            "advanced_title_filter": as_text(settings.get("advancedTitleFilter")),
            "location_filter": as_text(settings.get("locationFilter")),
            "description_filter": as_text(settings.get("descriptionFilter")),
            "organization_filter": as_text(settings.get("organizationFilter")),
            # Sin esto la API no devuelve el texto de la oferta y la AI no
            # tendria nada que evaluar.
            "description_type": as_text(settings.get("descriptionType"), "text"),
            "remote": as_bool(settings.get("remote")),
            "agency": as_bool(settings.get("includeAgencies")),
            "include_ai": as_bool(settings.get("includeAi")),
            "seniority_filter": as_text(settings.get("seniorityFilter")),
            "ai_work_arrangement_filter": as_text(settings.get("aiWorkArrangementFilter")),
            "ai_employment_type_filter": as_text(settings.get("aiEmploymentTypeFilter")),
            "ai_experience_level_filter": as_text(settings.get("aiExperienceLevelFilter")),
            "directapply": as_bool(settings.get("directApply")),
            "date_filter": as_text(settings.get("dateFilter")),
        }

    def fetch(self) -> FetchResult:
        payload = self.client.get_json(self._endpoint(), self.build_params())
        return map_items(_extract_items(payload), to_posting, NAME)


def _extract_items(payload: Any) -> List[Any]:
    """Saca la lista de trabajos del payload.

    Normalmente la API devuelve una lista directa, pero si algun dia la
    envuelve en un objeto (o devuelve un error con forma de dict), esto lo
    resuelve sin romper.
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

        message = as_text(first_present(payload, ["message", "error", "detail"]))
        if message:
            raise ProviderError(f"La API respondio con un error: {message}")

    return []


def build(settings: Dict[str, Any]) -> FantasticLinkedInSource:
    return FantasticLinkedInSource(settings)
