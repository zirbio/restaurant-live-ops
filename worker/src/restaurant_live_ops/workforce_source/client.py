"""Cliente HTTP de la fuente de personal con reintentos y cortacircuitos.

Autenticación: API key por cabecera si existe; si no, el formulario legacy
``POST /importer/login``, que devuelve una cookie ``JSESSIONID`` válida ocho
horas. Ante un 401 se reautentica una vez y se reintenta; si vuelve a fallar,
es un problema de credenciales y se propaga.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from restaurant_live_ops.config import WorkforceSourceSettings

MAX_RETRIES = 3
BACKOFF_SECONDS = (2.0, 4.0, 8.0)
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_RESPONSE_BYTES = 2_097_152
MAX_RESPONSE_ROWS = 10_000

# Tras tres fallos seguidos se corta cinco minutos: la fuente de personal no es nuestro y
# reintentar en bucle contra un sistema caído no ayuda a nadie.
CIRCUIT_THRESHOLD = 3
CIRCUIT_COOLDOWN_S = 300.0


class WorkforceSourceAuthError(RuntimeError):
    """Credenciales o sesión inválidas (401 persistente)."""


class ExternalSourceError(RuntimeError):
    """Fallo externo visible sin detalles sensibles de la petición o respuesta."""


class CircuitOpenError(RuntimeError):
    """El cortacircuitos está abierto: no se emiten peticiones."""


class WorkforceSourceClient:
    def __init__(
        self,
        settings: WorkforceSourceSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._sleep = sleep
        self._monotonic = monotonic
        self._client = httpx.AsyncClient(
            base_url=settings.base_url, transport=transport, timeout=60.0
        )
        self._authenticated = False
        self._consecutive_failures = 0
        self._open_until = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _authenticate(self) -> None:
        if self._settings.api_key:
            self._client.headers["Authorization"] = f"Bearer {self._settings.api_key}"
            self._authenticated = True
            return
        try:
            request = self._client.build_request(
                "POST",
                "/importer/login",
                data={"username": self._settings.username, "password": self._settings.password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response = await self._client.send(request, stream=True)
        except httpx.RequestError:
            self._record_failure()
            raise ExternalSourceError("workforce-source request failed") from None
        try:
            if response.status_code >= 400:
                raise WorkforceSourceAuthError(
                    f"el login de la fuente de personal devolvió {response.status_code}"
                )
        finally:
            await response.aclose()
        self._authenticated = True

    def _check_circuit(self) -> None:
        if self._consecutive_failures >= CIRCUIT_THRESHOLD:
            if self._monotonic() < self._open_until:
                raise CircuitOpenError(
                    "cortacircuitos de la fuente de personal abierto tras "
                    f"{self._consecutive_failures} fallos seguidos"
                )
            self._consecutive_failures = 0  # se agotó el enfriamiento: se reintenta

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= CIRCUIT_THRESHOLD:
            self._open_until = self._monotonic() + CIRCUIT_COOLDOWN_S

    async def get_json(self, path: str) -> Any:
        """GET con reintentos, reautenticación ante 401 y cortacircuitos."""
        self._check_circuit()
        if not self._authenticated:
            await self._authenticate()

        reauthenticated = False
        for intento in range(MAX_RETRIES):
            try:
                request = self._client.build_request("GET", path)
                response = await self._client.send(request, stream=True)
            except httpx.RequestError:
                # Conexión cortada, DNS o timeout: se reintenta de forma
                # acotada porque no describe la validez del dato solicitado.
                if intento < MAX_RETRIES - 1:
                    await self._sleep(BACKOFF_SECONDS[intento])
                    continue
                self._record_failure()
                raise ExternalSourceError("workforce-source request failed") from None

            if response.status_code == 401 and not reauthenticated:
                await response.aclose()
                reauthenticated = True
                self._authenticated = False
                await self._authenticate()
                continue
            if response.status_code == 401:
                await response.aclose()
                self._record_failure()
                raise WorkforceSourceAuthError(
                    "401 persistente de la fuente de personal tras reautenticar"
                )

            if response.status_code in RETRYABLE_STATUS and intento < MAX_RETRIES - 1:
                await response.aclose()
                await self._sleep(BACKOFF_SECONDS[intento])
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                await response.aclose()
                self._record_failure()
                raise ExternalSourceError(
                    f"workforce-source request failed with HTTP {response.status_code}"
                ) from None

            try:
                body = await self._read_limited_body(response)
                payload = json.loads(body)
            except ExternalSourceError:
                self._record_failure()
                raise
            except (ValueError, UnicodeDecodeError):
                self._record_failure()
                raise ExternalSourceError("workforce-source returned invalid JSON") from None
            finally:
                await response.aclose()
            if isinstance(payload, list) and len(payload) > MAX_RESPONSE_ROWS:
                self._record_failure()
                raise ExternalSourceError("workforce-source response exceeded row limit")
            self._consecutive_failures = 0
            return payload

        self._record_failure()
        raise ExternalSourceError("workforce-source request failed")

    async def _read_limited_body(self, response: httpx.Response) -> bytes:
        declared_length = response.headers.get("content-length")
        if declared_length is not None:
            try:
                length = int(declared_length)
            except ValueError:
                raise ExternalSourceError("workforce-source response has invalid length") from None
            if length < 0 or length > MAX_RESPONSE_BYTES:
                raise ExternalSourceError("workforce-source response exceeded byte limit")

        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                raise ExternalSourceError("workforce-source response exceeded byte limit")
            body.extend(chunk)
        return bytes(body)
