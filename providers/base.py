"""El contrato (puerto) que cumple cualquier fuente de trabajos.

Diseno: ports & adapters.

  - `JobSource` es un Protocol, no una clase base. Un proveedor no hereda de
    nada: basta con que tenga `name` y `fetch()`. Un stub en un test o un
    objeto falso tambien cumple el contrato.
  - El mapeo del JSON crudo al modelo `JobPosting` es una funcion pura
    (`Mapper`), sin red ni estado. Se testea con un JSON guardado en disco.
  - `fetch()` no lanza excepciones por datos malos: devuelve un `FetchResult`
    que dice cuantos trabajos se saltaron y por que.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, runtime_checkable

from models import JobPosting
from utils import append_to_log


class ProviderError(RuntimeError):
    """Falla de transporte o de configuracion: la busqueda completa no se pudo hacer.

    Un campo faltante NO es un ProviderError; eso se salta y se sigue.
    """


@dataclass
class FetchResult:
    """Resultado de una busqueda: lo que sirvio y lo que se descarto."""

    postings: List[JobPosting] = field(default_factory=list)
    received: int = 0
    skipped: int = 0
    warnings: List[str] = field(default_factory=list)
    # Cuota restante informada por la API, si la expone ("" si no).
    quota: str = ""

    def warn(self, message: str) -> None:
        self.skipped += 1
        if len(self.warnings) < 25:  # no llenamos la memoria si la API viene rota
            self.warnings.append(message)

    def summary(self) -> str:
        return f"{len(self.postings)} trabajos utiles de {self.received} recibidos ({self.skipped} descartados)"


@runtime_checkable
class JobSource(Protocol):
    """Puerto. Todo lo que el resto de la app necesita saber de una API."""

    name: str

    def fetch(self) -> FetchResult:
        ...


# Una funcion pura que convierte un item crudo de la API en JobPosting.
# Devuelve None si el item no sirve (sin titulo, sin empresa, etc).
Mapper = Callable[[Dict[str, Any]], Optional[JobPosting]]


def map_items(items: Iterable[Any], mapper: Mapper, source: str) -> FetchResult:
    """Aplica el mapper item por item, aislando las fallas.

    Aca vive la regla de robustez del proyecto: si un item revienta o le falta
    un campo obligatorio, se registra y se continua con el siguiente. Un item
    malo nunca bota la busqueda completa.
    """
    result = FetchResult()

    for index, item in enumerate(items or []):
        result.received += 1

        if not isinstance(item, dict):
            result.warn(f"[{source}] item #{index} no es un objeto JSON, se salta")
            continue

        try:
            posting = mapper(item)
        except Exception as error:  # el mapper nunca deberia lanzar, pero por si acaso
            result.warn(f"[{source}] item #{index} fallo al mapear: {type(error).__name__}: {error}")
            continue

        if posting is None:
            result.warn(f"[{source}] item #{index} sin datos minimos (titulo/empresa), se salta")
            continue

        posting.source = posting.source or source
        result.postings.append(posting)

    for warning in result.warnings:
        append_to_log(warning)

    return result
