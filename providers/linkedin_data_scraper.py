"""Adapter: LinkedIn Data Scraper (la API que usaba la app antes).

https://rapidapi.com/mgujjargamingm/api/linkedin-data-scraper

Se mantiene para poder volver atras cambiando `"provider"` en config.json, y
como segundo ejemplo de que agregar una API es solo un modulo mas.
"""

from typing import Any, Dict, List, Optional

from models import JobPosting
from providers.base import FetchResult, map_items
from providers.http import rapidapi_client
from utils.safe import as_text, clean_text, first_present

NAME = "linkedin_data_scraper"
HOST = "linkedin-data-scraper.p.rapidapi.com"
ENDPOINT = "search_jobs"

MAX_DESCRIPTION_CHARS = 20000


def to_posting(raw: Dict[str, Any]) -> Optional[JobPosting]:
    title = as_text(first_present(raw, ["title", "jobTitle"]))
    company = as_text(first_present(raw, ["companyName", "company", "companyUrn"]))

    if not title or not company:
        return None

    return JobPosting(
        title=title,
        company=company,
        url=as_text(first_present(raw, ["jobPostingUrl", "jobUrl", "url"])),
        description=clean_text(first_present(raw, ["jobDescription", "description"]), MAX_DESCRIPTION_CHARS),
        location=as_text(first_present(raw, ["formattedLocation", "location", "locationName"])),
        employment_type=as_text(first_present(raw, ["employmentStatus", "jobType"])),
        seniority=as_text(raw.get("experienceLevel")),
        posted_at=as_text(first_present(raw, ["postedAt", "listedAt", "originalListedAt"])),
        external_id=as_text(first_present(raw, ["jobPostingId", "id"])),
        source=NAME,
        raw=raw,
    )


class LinkedInDataScraperSource:
    name = NAME

    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings or {}
        self.client = rapidapi_client(HOST, self.settings)

    def build_params(self) -> Dict[str, Any]:
        settings = self.settings
        return {
            "query": as_text(settings.get("jobQuery")),
            "location": as_text(settings.get("jobLocation")),
            "searchLocationId": as_text(settings.get("searchLocationId")),
            # 1=Presencial, 2=Remoto, 3=Hibrido
            "workplaceType": as_text(settings.get("workplaceType")),
            # DD = mas recientes, R = mas relevantes
            "sortBy": as_text(settings.get("sortBy")),
            # F=Full time, P=Part time, C=Contract, T=Temporary, I=Internship...
            "jobType": as_text(settings.get("jobType")),
            "page": as_text(settings.get("page"), "1"),
            "easyApply": as_text(settings.get("easyApply"), "false"),
        }

    def fetch(self) -> FetchResult:
        payload = self.client.get_json(ENDPOINT, self.build_params())
        return map_items(_extract_items(payload), to_posting, NAME)


def _extract_items(payload: Any) -> List[Any]:
    """Esta API envuelve el resultado en {"response": {"jobs": [...]}}."""
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        response = payload.get("response")
        if isinstance(response, dict) and isinstance(response.get("jobs"), list):
            return response["jobs"]
        if isinstance(response, list):
            return response
        if isinstance(payload.get("jobs"), list):
            return payload["jobs"]

    return []


def build(settings: Dict[str, Any]) -> LinkedInDataScraperSource:
    return LinkedInDataScraperSource(settings)
