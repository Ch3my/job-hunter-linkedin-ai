"""Orquestacion de la busqueda: API -> AI -> base de datos.

Este modulo depende de los puertos (`JobSource`, `RelevanceClassifier`), no de
una API ni de un LLM concreto. Ambos se pueden inyectar, lo que permite
probarlo sin red.

Aislamiento de errores, de afuera hacia adentro:
  1. Si la API completa falla -> `ProviderError`, se reporta y la app sigue viva.
  2. Si un trabajo puntual viene mal -> el adapter lo salta (ver providers/base).
  3. Si la AI o el insert fallan en un trabajo -> se registra y se sigue con el
     siguiente. Un trabajo malo nunca corta la busqueda.
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from ai import RelevanceClassifier, create_classifier, is_relevant
from db import insert_job, job_exists
from models import JobPosting
from providers import FetchResult, JobSource, ProviderError, create_source
from utils import append_to_log, log_exception

StatusCallback = Callable[[str], None]


@dataclass
class HuntReport:
    """Que paso en esta corrida. La UI lo usa para el mensaje de estado."""

    received: int = 0
    skipped_by_api: int = 0
    already_known: int = 0
    not_relevant: int = 0
    inserted: int = 0
    failed: int = 0
    new_jobs: List[JobPosting] = field(default_factory=list)
    error: str = ""
    ai_notice: str = ""

    def message(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        resumen = (
            f"{self.inserted} nuevos | {self.already_known} ya guardados | "
            f"{self.not_relevant} descartados por AI | {self.received} revisados"
        )
        # Si la AI no filtro, hay que decirlo: si no, parece que el prompt.txt
        # se aplico cuando en realidad se guardo todo.
        return f"{resumen}  ({self.ai_notice})" if self.ai_notice else resumen


def job_hunt(
    source: Optional[JobSource] = None,
    classifier: Optional[RelevanceClassifier] = None,
    on_status: Optional[StatusCallback] = None,
) -> HuntReport:
    """Ejecuta una busqueda completa y devuelve el resumen.

    No lanza excepciones: los problemas quedan en `report.error`.
    """
    report = HuntReport()

    def status(message: str) -> None:
        if on_status:
            try:
                on_status(message)
            except Exception:
                pass  # un problema al pintar la UI no puede cortar la busqueda

    # --- 1. Traer los trabajos -------------------------------------------
    try:
        source = source or create_source()
        status(f"Consultando {source.name}...")
        result: FetchResult = source.fetch()
    except ProviderError as error:
        report.error = str(error)
        append_to_log(f"[job_hunt] {error}")
        return report
    except Exception as error:
        report.error = f"Error inesperado al consultar la API: {error}"
        log_exception("job_hunt.fetch", error)
        return report

    report.received = result.received
    report.skipped_by_api = result.skipped
    append_to_log(f"[job_hunt] {source.name}: {result.summary()}")

    if not result.postings:
        status("La busqueda no devolvio trabajos utilizables.")
        return report

    # --- 2. Evaluar y guardar, uno por uno -------------------------------
    classifier = classifier or create_classifier()
    report.ai_notice = getattr(classifier, "reason", "") or ""
    if report.ai_notice:
        status(report.ai_notice)

    total = len(result.postings)

    for index, posting in enumerate(result.postings, start=1):
        status(f"Evaluando {index}/{total}: {posting.title[:60]}")

        try:
            # Si ya esta en la base no gastamos una llamada al LLM.
            if job_exists(posting.title, posting.company):
                report.already_known += 1
                continue

            posting.relevant = classifier.classify(posting)
            if not is_relevant(posting.relevant):
                report.not_relevant += 1
                continue

            if insert_job(posting):
                report.inserted += 1
                report.new_jobs.append(posting)
            else:
                report.already_known += 1

        except Exception as error:
            # Cualquier sorpresa con este trabajo: se anota y se sigue.
            report.failed += 1
            log_exception(f"job_hunt[{posting.title} @ {posting.company}]", error)
            continue

    append_to_log(f"[job_hunt] {report.message()}")
    status(report.message())
    return report
