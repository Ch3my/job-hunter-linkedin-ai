"""Registro de proveedores.

En Python una "factory" es un diccionario. Para sumar una API nueva:

  1. Crear `providers/mi_api.py` con una clase que tenga `name` y `fetch()`,
     y una funcion `build(settings) -> esa clase`.
  2. Agregar una linea en `BUILDERS`.
  3. Poner `"provider": "mi_api"` en config.json.

Nada mas del proyecto cambia.
"""

from typing import Any, Callable, Dict, List

from config import active_provider_name, load_config, provider_settings
from providers import fantastic_linkedin, linkedin_data_scraper
from providers.base import JobSource, ProviderError

Builder = Callable[[Dict[str, Any]], JobSource]

BUILDERS: Dict[str, Builder] = {
    fantastic_linkedin.NAME: fantastic_linkedin.build,
    linkedin_data_scraper.NAME: linkedin_data_scraper.build,
}


def available_sources() -> List[str]:
    return sorted(BUILDERS)


def create_source(name: str = None, config: Dict[str, Any] = None) -> JobSource:
    """Construye la fuente de trabajos configurada.

    Sin argumentos usa el proveedor activo de config.json.
    """
    config = config or load_config()
    name = (name or active_provider_name(config)).strip()

    builder = BUILDERS.get(name)
    if builder is None:
        raise ProviderError(
            f"Proveedor '{name}' desconocido. Disponibles: {', '.join(available_sources())}"
        )

    return builder(provider_settings(name, config))
