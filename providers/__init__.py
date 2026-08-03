"""Capa de acceso a APIs de trabajos (ports & adapters).

El resto de la aplicacion importa solo desde aca:

    from providers import create_source
    result = create_source().fetch()   # -> FetchResult con JobPosting

y nunca ve el JSON crudo de ninguna API.
"""

from providers.base import FetchResult, JobSource, ProviderError, map_items
from providers.registry import available_sources, create_source

__all__ = [
    "FetchResult",
    "JobSource",
    "ProviderError",
    "map_items",
    "available_sources",
    "create_source",
]
