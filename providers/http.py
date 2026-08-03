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
from dataclasses import dataclass, field
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
    # Cabeceras de la ultima respuesta, para leer la cuota restante.
    last_headers: Dict[str, str] = field(default_factory=dict)

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self._build_url(path, params)
        last_error = "sin detalle"

        for attempt in range(1, max(1, self.max_retries) + 1):
            try:
                request = urllib.request.Request(url, headers=self.headers, method="GET")
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read()
                    self.last_headers = {k.lower(): v for k, v in response.headers.items()}
                return self._decode(body)

            except urllib.error.HTTPError as error:
                # Las respuestas de error tambien traen las cabeceras de cuota:
                # es justo cuando mas util es saber cuanto queda.
                self.last_headers = {k.lower(): v for k, v in error.headers.items()}
                detail = self._error_body(error)
                last_error = f"HTTP {error.code}: {detail}"

                if error.code in (401, 403):
                    raise ProviderError(
                        f"La API rechazo la credencial (HTTP {error.code}). "
                        f"Revisa 'rapidApiKey' en config.json. {detail}"
                    ) from error

                if error.code == 429 and not self._quota_left():
                    # Reintentar no sirve: la cuota del plan esta agotada.
                    raise ProviderError(
                        f"Se agoto la cuota del plan. {self.quota_summary()}. {detail}"
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

    def quota(self) -> Dict[str, Optional[int]]:
        """Creditos restantes segun las cabeceras de la ultima respuesta.

        La API devuelve dos contadores distintos: "jobs" (se descuenta un
        credito por cada trabajo devuelto) y "requests" (uno por llamada). El
        de jobs es el que se agota primero, por diseno.
        """
        def leer(nombre: str) -> Optional[int]:
            try:
                return int(self.last_headers.get(nombre, ""))
            except (TypeError, ValueError):
                return None

        return {
            "jobs_remaining": leer("x-ratelimit-jobs-remaining"),
            "jobs_limit": leer("x-ratelimit-jobs-limit"),
            "requests_remaining": leer("x-ratelimit-requests-remaining"),
            "requests_limit": leer("x-ratelimit-requests-limit"),
            "reset_seconds": leer("x-ratelimit-jobs-reset"),
        }

    def _quota_left(self) -> bool:
        """False si algun contador de cuota llego a cero (reintentar no sirve)."""
        q = self.quota()
        for key in ("jobs_remaining", "requests_remaining"):
            if q[key] is not None and q[key] <= 0:
                return False
        return True

    def quota_summary(self) -> str:
        """Texto corto con la cuota, o "" si la API no mando las cabeceras."""
        q = self.quota()
        if q["jobs_remaining"] is None and q["requests_remaining"] is None:
            return ""

        partes = []
        if q["jobs_remaining"] is not None:
            total = f"/{q['jobs_limit']}" if q["jobs_limit"] else ""
            partes.append(f"jobs {q['jobs_remaining']}{total}")
        if q["requests_remaining"] is not None:
            total = f"/{q['requests_limit']}" if q["requests_limit"] else ""
            partes.append(f"requests {q['requests_remaining']}{total}")
        if q["reset_seconds"]:
            partes.append(f"renueva en {q['reset_seconds'] // 86400}d")
        return "cuota restante: " + ", ".join(partes)

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
