"""Cliente HTTP compartido por los proveedores.

Se separa a proposito del mapeo de datos: reintentos, timeouts y manejo de
errores se escriben una sola vez, y agregar una API nueva significa solo armar
sus parametros y mapear sus campos.

Usa solo la libreria estandar para no sumar dependencias al ejecutable.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

from providers.base import ProviderError
from utils import append_to_log

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass
class HttpClient:
    """GET de JSON con reintentos y backoff exponencial."""

    host: str
    headers: Dict[str, str]
    timeout: int = 30
    max_retries: int = 3
    backoff_seconds: float = 1.5

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self._build_url(path, params)
        last_error = "sin detalle"

        for attempt in range(1, max(1, self.max_retries) + 1):
            try:
                request = urllib.request.Request(url, headers=self.headers, method="GET")
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read()
                return self._decode(body)

            except urllib.error.HTTPError as error:
                detail = self._error_body(error)
                last_error = f"HTTP {error.code}: {detail}"
                if error.code in (401, 403):
                    raise ProviderError(
                        f"La API rechazo la credencial (HTTP {error.code}). "
                        f"Revisa 'rapidApiKey' en config.json. {detail}"
                    ) from error
                if error.code not in RETRY_STATUS:
                    raise ProviderError(f"La API respondio {error.code}. {detail}") from error

            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last_error = f"{type(error).__name__}: {error}"

            except json.JSONDecodeError as error:
                raise ProviderError(f"La API devolvio algo que no es JSON valido: {error}") from error

            if attempt < self.max_retries:
                wait = self.backoff_seconds * (2 ** (attempt - 1))
                append_to_log(f"[http] intento {attempt}/{self.max_retries} fallo ({last_error}), reintentando en {wait:.1f}s")
                time.sleep(wait)

        raise ProviderError(f"No se pudo contactar {self.host} tras {self.max_retries} intentos. Ultimo error: {last_error}")

    def _build_url(self, path: str, params: Optional[Dict[str, Any]]) -> str:
        clean = {}
        for key, value in (params or {}).items():
            # None / "" significa "no mandar este parametro".
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                clean[key] = "true" if value else "false"
            else:
                clean[key] = str(value)

        path = "/" + path.lstrip("/")
        query = urllib.parse.urlencode(clean)
        return f"https://{self.host}{path}" + (f"?{query}" if query else "")

    @staticmethod
    def _decode(body: bytes) -> Any:
        if not body:
            return []
        try:
            return json.loads(body.decode("utf-8"))
        except UnicodeDecodeError:
            return json.loads(body.decode("utf-8", errors="replace"))

    @staticmethod
    def _error_body(error: urllib.error.HTTPError) -> str:
        try:
            raw = error.read().decode("utf-8", errors="replace")
        except Exception:
            return ""
        raw = raw.strip()
        if len(raw) > 300:
            raw = raw[:300] + "..."
        return raw


def rapidapi_client(host: str, settings: Dict[str, Any]) -> HttpClient:
    """Arma un HttpClient con las cabeceras que pide RapidAPI."""
    api_key = str(settings.get("apiKey") or "").strip()
    if not api_key:
        raise ProviderError("Falta 'rapidApiKey' en config.json.")

    return HttpClient(
        host=host,
        headers={
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": host,
            "Accept": "application/json",
        },
        timeout=int(settings.get("requestTimeout") or 30),
        max_retries=int(settings.get("maxRetries") or 3),
    )
