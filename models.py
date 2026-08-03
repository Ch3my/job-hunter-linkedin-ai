"""Modelo canonico de la aplicacion.

Todo lo que esta fuera de `providers/` trabaja con `JobPosting`, nunca con el
JSON crudo de una API. Asi, cambiar de proveedor no obliga a tocar la base de
datos, la AI ni la interfaz.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# La politica de identidad vive en su propio modulo: es una decision de la app,
# no de un proveedor ni parte de la forma del dato. Ver identity.py.
from identity import build_job_key

NOT_APPLIED = "Not applied"
APPLIED = "Applied"
DISCARDED = "Discarded"
STATUSES = (NOT_APPLIED, APPLIED, DISCARDED)


@dataclass
class JobPosting:
    """Una oferta de trabajo, ya normalizada."""

    title: str = ""
    company: str = ""
    url: str = ""
    description: str = ""
    location: str = ""
    employment_type: str = ""
    seniority: str = ""
    salary: str = ""
    posted_at: str = ""
    external_id: str = ""
    source: str = ""
    applied: str = NOT_APPLIED
    # Veredicto de la AI. `score` es 0-100; -1 significa "no evaluado" (no habia
    # AI configurada, o el LLM fallo y el trabajo paso por la politica de duda).
    relevant: str = ""
    score: int = -1
    reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def key(self) -> str:
        """Clave logica: la misma que usa la tabla (titulo + empresa normalizados)."""
        return build_job_key(self.title, self.company)

    def is_valid(self) -> bool:
        """Sin titulo o sin empresa no se puede guardar (son la PK)."""
        return bool(self.title.strip()) and bool(self.company.strip())

    def text_for_ai(self) -> str:
        """Texto que se le manda al clasificador.

        Si la API no trajo descripcion igual mandamos algo util en vez de
        saltarnos el trabajo o mandar un string vacio.
        """
        parts = [
            f"Cargo: {self.title}" if self.title else "",
            f"Empresa: {self.company}" if self.company else "",
            f"Ubicacion: {self.location}" if self.location else "",
            f"Jornada: {self.employment_type}" if self.employment_type else "",
            f"Seniority: {self.seniority}" if self.seniority else "",
            f"Renta: {self.salary}" if self.salary else "",
        ]
        header = "\n".join(part for part in parts if part)
        body = self.description or "(sin descripcion disponible)"
        return f"{header}\n\n{body}".strip()

    def description_for_storage(self) -> str:
        """Descripcion a persistir; si no hay, se arma un resumen con lo que si vino."""
        if self.description.strip():
            return self.description.strip()
        summary = [
            f"Ubicacion: {self.location}" if self.location else "",
            f"Jornada: {self.employment_type}" if self.employment_type else "",
            f"Seniority: {self.seniority}" if self.seniority else "",
            f"Renta: {self.salary}" if self.salary else "",
            f"Publicado: {self.posted_at}" if self.posted_at else "",
            f"Fuente: {self.source}" if self.source else "",
        ]
        summary = [line for line in summary if line]
        if not summary:
            return "(La API no entrego descripcion para este trabajo)"
        return "(La API no entrego descripcion para este trabajo)\n\n" + "\n".join(summary)


def make_manual_posting(
    title: str,
    company: str,
    url: str = "",
    description: str = "",
    applied: Optional[str] = None,
) -> JobPosting:
    """Crea un JobPosting desde la UI (carga manual)."""
    return JobPosting(
        title=title.strip(),
        company=company.strip(),
        url=url.strip(),
        description=description,
        applied=applied if applied in STATUSES else NOT_APPLIED,
        source="manual",
    )
