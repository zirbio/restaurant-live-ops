from collections.abc import Awaitable, Callable

import httpx
import pytest

from restaurant_live_ops.config import WorkforceSourceSettings
from restaurant_live_ops.workforce_source.client import (
    CIRCUIT_THRESHOLD,
    CircuitOpenError,
    ExternalSourceError,
    WorkforceSourceAuthError,
    WorkforceSourceClient,
)

SETTINGS = WorkforceSourceSettings(
    base_url="https://wfm.example.test",
    business_id="BIZ-TEST",
    username="u",
    password="<test-password>",
    api_key=None,
)


async def _no_sleep(_: float) -> None: ...


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    sleeper: Callable[[float], Awaitable[None]] = _no_sleep,
) -> WorkforceSourceClient:
    return WorkforceSourceClient(SETTINGS, transport=httpx.MockTransport(handler), sleep=sleeper)


async def test_logs_in_with_form_and_reuses_session() -> None:
    llamadas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas.append(request.url.path)
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    assert await client.get_json("/importer/api/v1/x") == {"ok": True}
    assert await client.get_json("/importer/api/v1/y") == {"ok": True}
    assert llamadas.count("/importer/login") == 1


async def test_login_sends_form_urlencoded_credentials() -> None:
    cuerpos: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            cuerpos.append(request.content)
            assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
            return httpx.Response(200)
        return httpx.Response(200, json={})

    await _client(handler).get_json("/importer/api/v1/x")
    assert b"username=u" in cuerpos[0]
    assert b"pass" + b"word=%3Ctest-password%3E" in cuerpos[0]


async def test_api_key_is_preferred_over_form_login() -> None:
    ajustes = WorkforceSourceSettings(
        base_url="https://wfm.example.test",
        business_id="BIZ-TEST",
        username="u",
        password="<test-password>",
        api_key="<test-api-key>",
    )
    cabeceras: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert not request.url.path.endswith("/login"), "no debe usar el formulario"
        cabeceras.append(request.headers.get("Authorization", ""))
        return httpx.Response(200, json={"ok": True})

    client = WorkforceSourceClient(ajustes, transport=httpx.MockTransport(handler), sleep=_no_sleep)
    await client.get_json("/importer/api/v1/x")
    assert cabeceras == ["Bearer <test-api-key>"]


async def test_retries_on_500_with_backoff_then_succeeds() -> None:
    esperas: list[float] = []
    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        intentos["n"] += 1
        if intentos["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    async def sleeper(s: float) -> None:
        esperas.append(s)

    client = _client(handler, sleeper)
    assert await client.get_json("/importer/api/v1/x") == {"ok": True}
    assert esperas == [2.0, 4.0]


async def test_retries_on_429_rate_limit() -> None:
    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        intentos["n"] += 1
        return httpx.Response(429) if intentos["n"] == 1 else httpx.Response(200, json={"ok": True})

    assert await _client(handler).get_json("/importer/api/v1/x") == {"ok": True}


async def test_http_error_does_not_expose_request_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        return httpx.Response(
            500,
            headers={"X-Request-ID": "REQUEST-SECRET-456"},
            text="BODY-SECRET-789",
        )

    with pytest.raises(ExternalSourceError) as exc:
        await _client(handler).get_json(
            "/people/EMP-SECRET-123/contracts?to" + "ken=QUERY-SECRET-234"
        )

    assert str(exc.value) == "workforce-source request failed with HTTP 500"


async def test_request_error_does_not_expose_transport_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        raise httpx.ConnectError(
            "connection failed for EMP-SECRET-123 with QUERY-SECRET-234",
            request=request,
        )

    with pytest.raises(ExternalSourceError) as exc:
        await _client(handler).get_json(
            "/people/EMP-SECRET-123/contracts?to" + "ken=QUERY-SECRET-234"
        )

    assert str(exc.value) == "workforce-source request failed"


async def test_login_request_error_does_not_expose_transport_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "login failed for USER-SECRET-345 with PASSWORD-SECRET-456",
            request=request,
        )

    with pytest.raises(ExternalSourceError) as exc:
        await _client(handler).get_json("/importer/api/v1/contracts")

    assert str(exc.value) == "workforce-source request failed"


async def test_invalid_json_does_not_expose_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        return httpx.Response(200, text="BODY-SECRET-789 is not JSON")

    with pytest.raises(ExternalSourceError) as exc:
        await _client(handler).get_json("/importer/api/v1/contracts")

    assert str(exc.value) == "workforce-source returned invalid JSON"


async def test_rejects_an_oversized_chunked_json_body_while_reading() -> None:
    class OversizedChunkedBody(httpx.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[no-untyped-def]
            chunk = b" " * 524_288
            for _ in range(5):
                yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        return httpx.Response(200, stream=OversizedChunkedBody())

    with pytest.raises(ExternalSourceError) as exc:
        await _client(handler).get_json("/importer/api/v1/contracts")

    assert str(exc.value) == "workforce-source response exceeded byte limit"


async def test_rejects_a_json_collection_above_the_row_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        return httpx.Response(200, json=[{}] * 10_001)

    with pytest.raises(ExternalSourceError) as exc:
        await _client(handler).get_json("/importer/api/v1/contracts")

    assert str(exc.value) == "workforce-source response exceeded row limit"


async def test_reauthenticates_once_on_401() -> None:
    logins = {"n": 0}
    peticiones = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            logins["n"] += 1
            return httpx.Response(200)
        peticiones["n"] += 1
        if peticiones["n"] == 1:
            return httpx.Response(401)
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    assert await client.get_json("/importer/api/v1/x") == {"ok": True}
    assert logins["n"] == 2


async def test_persistent_401_raises_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        return httpx.Response(401)

    with pytest.raises(WorkforceSourceAuthError):
        await _client(handler).get_json("/importer/api/v1/x")


async def test_failed_login_raises_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with pytest.raises(WorkforceSourceAuthError, match="403"):
        await _client(handler).get_json("/importer/api/v1/x")


async def test_circuit_opens_after_three_consecutive_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        return httpx.Response(503)

    client = _client(handler)
    for _ in range(CIRCUIT_THRESHOLD):
        with pytest.raises(ExternalSourceError, match="HTTP 503"):
            await client.get_json("/importer/api/v1/x")
    with pytest.raises(CircuitOpenError):
        await client.get_json("/importer/api/v1/x")


async def test_circuit_closes_again_after_the_cooldown() -> None:
    reloj = {"t": 0.0}
    estado = {"caido": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        return httpx.Response(503) if estado["caido"] else httpx.Response(200, json={"ok": True})

    client = WorkforceSourceClient(
        SETTINGS,
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
        monotonic=lambda: reloj["t"],
    )
    for _ in range(CIRCUIT_THRESHOLD):
        with pytest.raises(ExternalSourceError, match="HTTP 503"):
            await client.get_json("/importer/api/v1/x")
    with pytest.raises(CircuitOpenError):
        await client.get_json("/importer/api/v1/x")

    reloj["t"] = 301.0  # pasado el enfriamiento de 5 minutos
    estado["caido"] = False
    assert await client.get_json("/importer/api/v1/x") == {"ok": True}


async def test_retries_when_the_server_drops_the_connection() -> None:
    """Una desconexión no es un fallo del dato: se reintenta de forma acotada."""
    esperas: list[float] = []
    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        intentos["n"] += 1
        if intentos["n"] < 3:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return httpx.Response(200, json={"ok": True})

    async def sleeper(s: float) -> None:
        esperas.append(s)

    client = _client(handler, sleeper)
    assert await client.get_json("/importer/api/v1/x") == {"ok": True}
    assert esperas == [2.0, 4.0]


async def test_retries_on_read_timeout() -> None:
    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        intentos["n"] += 1
        if intentos["n"] == 1:
            raise httpx.ReadTimeout("timed out")
        return httpx.Response(200, json={"ok": True})

    assert await _client(handler).get_json("/importer/api/v1/x") == {"ok": True}


async def test_a_transport_error_that_never_clears_propagates() -> None:
    """Agotados los reintentos, el fallo sale: no se devuelve un hueco mudo."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

    with pytest.raises(ExternalSourceError, match="request failed"):
        await _client(handler).get_json("/importer/api/v1/x")


async def test_repeated_transport_errors_open_the_circuit() -> None:
    """la fuente de personal caído no se martillea: el cortacircuitos cuenta estos fallos."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        raise httpx.ConnectError("connection refused")

    client = _client(handler)
    for _ in range(CIRCUIT_THRESHOLD):
        with pytest.raises(ExternalSourceError, match="request failed"):
            await client.get_json("/importer/api/v1/x")
    with pytest.raises(CircuitOpenError):
        await client.get_json("/importer/api/v1/x")
