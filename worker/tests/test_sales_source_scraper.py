import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import pytest

import restaurant_live_ops.sales_source.scraper as scraper_module
from restaurant_live_ops.config import SalesSourceSettings
from restaurant_live_ops.restaurants import Restaurant
from restaurant_live_ops.sales_source.date_header import StaleDateError
from restaurant_live_ops.sales_source.scraper import (
    HOURLY_FIELD_MARKER,
    HourlyCatcher,
    ensure_date,
    picker_month,
)


@dataclass
class FakeResponse:
    url: str
    text_body: str
    headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = {"content-length": str(len(self.text_body.encode()))}

    async def text(self) -> str:
        return self.text_body

    async def body(self) -> bytes:
        return self.text_body.encode()


def _payload(fields: list[str], success: bool = True) -> str:
    return json.dumps({"success": success, "metaData": {"fields": fields}, "rows": []})


def _hourly_url() -> str:
    return "https://source.test/events/HandleEvent" + "?Obj=hourly-grid&Evt=data"


def _url(*parts: str) -> str:
    return "".join(parts)


def _catcher() -> HourlyCatcher:
    return HourlyCatcher(_hourly_url())


async def _noop_close_capture() -> None:
    pass


class _CaptureRequest:
    url = _hourly_url()

    def __init__(self, hour: str = "9", net: str = "20") -> None:
        self.response_calls = 0
        self.linked_response = FakeResponse(
            _hourly_url(),
            json.dumps(
                {
                    "success": True,
                    "metaData": {"fields": ["0", "12"]},
                    "rows": [{"0": hour, "1": net, "_s0": "Total", "_s1": net}],
                }
            ),
        )
        self.linked_response.request = self  # type: ignore[attr-defined]

    async def response(self) -> FakeResponse:
        self.response_calls += 1
        return self.linked_response


async def _resolved_request(request: _CaptureRequest | None) -> _CaptureRequest:
    if request is None:
        raise TimeoutError("no exact request")
    return request


class _PendingCaptureRequest:
    def __init__(self, request: _CaptureRequest | None) -> None:
        self.request = request

    async def __aenter__(self) -> "_PendingCaptureRequest":
        self.value = _resolved_request(self.request)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _CapturePage:
    def __init__(
        self,
        plans: list[tuple[list[_CaptureRequest], list[_CaptureRequest]]],
        *,
        delayed_requests: list[tuple[float, _CaptureRequest]] | None = None,
    ) -> None:
        self.request_listeners: list[object] = []
        self.plans = plans
        self.delayed_requests = delayed_requests or []
        self.delayed_handles: list[asyncio.TimerHandle] = []
        self.late_emitted = False
        self.closed = False

    class Card:
        def __init__(self, page: "_CapturePage") -> None:
            self.page = page

        @property
        def first(self) -> "_CapturePage.Card":
            return self

        async def click(self, *, timeout: int) -> None:
            assert timeout == 10_000
            immediate, scheduled = self.page.plans.pop(0)
            for request in immediate:
                self.page.emit_request(request)
            for request in scheduled:
                asyncio.get_running_loop().call_soon(self.page.emit_late_request, request)
            for delay, request in self.page.delayed_requests:
                handle = asyncio.get_running_loop().call_later(
                    delay, self.page.emit_late_request, request
                )
                self.page.delayed_handles.append(handle)
            self.page.delayed_requests.clear()

    def emit_request(self, request: _CaptureRequest) -> None:
        for listener in tuple(self.request_listeners):
            assert callable(listener)
            listener(request)

    def emit_late_request(self, request: _CaptureRequest) -> None:
        self.late_emitted = True
        self.emit_request(request)

    def get_by_text(self, _text: str, *, exact: bool) -> "_CapturePage.Card":
        assert exact
        return self.Card(self)

    def expect_request(self, predicate: object, *, timeout: int) -> _PendingCaptureRequest:
        immediate, scheduled = self.plans[0]
        requests = immediate + scheduled
        assert callable(predicate)
        assert all(predicate(request) for request in requests)
        assert timeout == 20_000
        return _PendingCaptureRequest(requests[0] if requests else None)

    def on(self, event: str, listener: object) -> None:
        assert event == "request"
        self.request_listeners.append(listener)

    def remove_listener(self, event: str, listener: object) -> None:
        assert event == "request"
        self.request_listeners.remove(listener)

    async def close(self) -> None:
        assert self.request_listeners
        await asyncio.sleep(0)
        for handle in self.delayed_handles:
            handle.cancel()
        self.closed = True


async def test_keeps_hourly_payload() -> None:
    catcher = _catcher()
    selection = catcher.begin_capture("R001")

    payload = await catcher.capture(FakeResponse(_hourly_url(), _payload(["0", "12"])), selection)

    assert payload["success"] is True


async def test_ignores_nine_column_start_grid() -> None:
    # Las grids de la pantalla Start traen 9 columnas: no llevan el marcador "12".
    catcher = _catcher()
    selection = catcher.begin_capture("R001")
    with pytest.raises(ValueError, match="respuesta horaria inválida"):
        await catcher.capture(FakeResponse(_hourly_url(), _payload(["0", "8"])), selection)


async def test_ignores_unsuccessful_payload() -> None:
    catcher = _catcher()
    selection = catcher.begin_capture("R001")
    with pytest.raises(ValueError, match="respuesta horaria inválida"):
        await catcher.capture(
            FakeResponse(_hourly_url(), _payload(["0", "12"], success=False)), selection
        )


async def test_ignores_unrelated_urls() -> None:
    catcher = _catcher()
    for url in (
        _url("https:/", "/other.test/events/HandleEvent?Obj=hourly-grid&Evt=data"),
        _url("https:/", "/source.test/other/HandleEvent?Obj=hourly-grid&Evt=data"),
        _url("https:/", "/source.test/events/HandleEvent?Evt=data&Obj=other-grid"),
        _url("https:/", "/source.test/events/HandleEvent?Obj=hourly-grid&Evt=data&extra=1"),
    ):
        selection = catcher.begin_capture("R001")
        assert not catcher.matches(FakeResponse(url, _payload(["0", "12"])))
        with pytest.raises(ValueError, match="respuesta horaria no correlacionada"):
            await catcher.capture(FakeResponse(url, _payload(["0", "12"])), selection)


async def test_non_json_body_is_ignored_without_raising() -> None:
    catcher = _catcher()
    selection = catcher.begin_capture("R001")
    with pytest.raises(ValueError, match="respuesta horaria inválida"):
        await catcher.capture(FakeResponse(_hourly_url(), "<html>"), selection)


async def test_rejects_a_response_linked_to_an_old_selection() -> None:
    catcher = _catcher()
    old_selection = catcher.begin_capture("R001")
    catcher.begin_capture("R002")

    with pytest.raises(ValueError, match="selección actual"):
        await catcher.capture(FakeResponse(_hourly_url(), _payload(["0", "12"])), old_selection)


async def test_rejects_oversized_chunked_body_and_too_many_rows() -> None:
    catcher = _catcher()
    selection = catcher.begin_capture("R001")

    class BodyMustNotBeRead:
        url = _hourly_url()

        def __init__(self) -> None:
            self.headers = {"transfer-encoding": "chunked"}

        async def body(self) -> bytes:
            raise AssertionError("body() no debe ejecutarse sin longitud fiable")

    with pytest.raises(ValueError, match="longitud fiable"):
        await catcher.capture(BodyMustNotBeRead(), selection)

    selection = catcher.begin_capture("R001")
    too_many_rows = json.dumps(
        {
            "success": True,
            "metaData": {"fields": ["0", "12"]},
            "rows": [{"0": hour} for hour in range(97)],
        }
    )
    with pytest.raises(ValueError, match="límite de filas"):
        await catcher.capture(FakeResponse(_hourly_url(), too_many_rows), selection)


async def test_rejects_a_body_whose_real_size_differs_from_content_length() -> None:
    catcher = _catcher()
    selection = catcher.begin_capture("R001")
    response = FakeResponse(
        _hourly_url(),
        _payload(["0", "12"]),
        headers={"content-length": "1"},
    )

    with pytest.raises(ValueError, match="longitud inconsistente"):
        await catcher.capture(response, selection)


async def test_capture_awaits_the_response_of_the_request_started_during_the_click() -> None:
    stale_response = FakeResponse(
        _hourly_url(),
        json.dumps(
            {
                "success": True,
                "metaData": {"fields": ["0", "12"]},
                "rows": [{"0": "8", "1": "10", "_s0": "Total", "_s1": "10"}],
            }
        ),
    )
    new_response = FakeResponse(
        _hourly_url(),
        json.dumps(
            {
                "success": True,
                "metaData": {"fields": ["0", "12"]},
                "rows": [{"0": "9", "1": "20", "_s0": "Total", "_s1": "20"}],
            }
        ),
    )

    class FakeRequest:
        url = _hourly_url()

        def __init__(self) -> None:
            self.response_calls = 0

        async def response(self) -> FakeResponse:
            self.response_calls += 1
            return new_response

    request = FakeRequest()
    new_response.request = request  # type: ignore[attr-defined]

    class PendingEvent:
        def __init__(self, value: object) -> None:
            self.value = _resolved(value)

        async def __aenter__(self) -> "PendingEvent":
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    async def _resolved(value: object) -> object:
        return value

    class Card:
        def __init__(self, page: "FakePage") -> None:
            self.page = page

        @property
        def first(self) -> "Card":
            return self

        async def click(self, *, timeout: int) -> None:
            assert timeout == 10_000
            for listener in tuple(self.page.request_listeners):
                assert callable(listener)
                listener(request)

    class FakePage:
        used_response_listener = False

        def __init__(self) -> None:
            self.request_listeners: list[object] = []

        def get_by_text(self, _text: str, *, exact: bool) -> Card:
            assert exact
            return Card(self)

        def expect_response(self, predicate: object, *, timeout: int) -> PendingEvent:
            self.used_response_listener = True
            assert callable(predicate) and predicate(stale_response)
            assert timeout == 20_000
            return PendingEvent(stale_response)

        def expect_request(self, predicate: object, *, timeout: int) -> PendingEvent:
            assert callable(predicate) and predicate(request)
            assert timeout == 20_000
            return PendingEvent(request)

        def on(self, event: str, listener: object) -> None:
            assert event == "request"
            self.request_listeners.append(listener)

        def remove_listener(self, event: str, listener: object) -> None:
            assert event == "request"
            self.request_listeners.remove(listener)

    page = FakePage()
    day = await scraper_module._capture_restaurant(
        page,  # type: ignore[arg-type]
        _catcher(),
        Restaurant("R001", "Central", "Central card", 1, True),
        date(2030, 1, 15),
        close_capture=_noop_close_capture,
    )

    assert page.used_response_listener is False
    assert request.response_calls == 1
    assert day is not None
    assert [row.net for row in day.hours] == [20]
    assert page.request_listeners == []


@pytest.mark.parametrize("ambiguous", [False, True])
async def test_capture_rejects_a_request_without_one_inequivocal_response(
    ambiguous: bool,
) -> None:
    class FakeRequest:
        url = _hourly_url()

        async def response(self) -> FakeResponse | None:
            return response if ambiguous else None

    request = FakeRequest()
    other_request = FakeRequest()
    response = FakeResponse(_hourly_url(), _payload(["0", "12"]))
    response.request = other_request  # type: ignore[attr-defined]

    class PendingRequest:
        value = request.response() if False else None

        async def __aenter__(self) -> "PendingRequest":
            self.value = _resolved(request)
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    async def _resolved(value: object) -> object:
        return value

    class Card:
        def __init__(self, page: "FakePage") -> None:
            self.page = page

        @property
        def first(self) -> "Card":
            return self

        async def click(self, *, timeout: int) -> None:
            assert timeout == 10_000
            for listener in tuple(self.page.request_listeners):
                assert callable(listener)
                listener(request)

    class FakePage:
        def __init__(self) -> None:
            self.request_listeners: list[object] = []

        def get_by_text(self, _text: str, *, exact: bool) -> Card:
            return Card(self)

        def expect_request(self, predicate: object, *, timeout: int) -> PendingRequest:
            assert callable(predicate) and predicate(request)
            assert timeout == 20_000
            return PendingRequest()

        def on(self, event: str, listener: object) -> None:
            assert event == "request"
            self.request_listeners.append(listener)

        def remove_listener(self, event: str, listener: object) -> None:
            assert event == "request"
            self.request_listeners.remove(listener)

    with pytest.raises(ValueError, match="respuesta inequívoca"):
        await scraper_module._capture_restaurant(
            FakePage(),  # type: ignore[arg-type]
            _catcher(),
            Restaurant("R001", "Central", "Central card", 1, True),
            date(2030, 1, 15),
            close_capture=_noop_close_capture,
        )


async def test_capture_rejects_two_exact_requests_emitted_by_the_same_click() -> None:
    class FakeRequest:
        url = _hourly_url()

        def __init__(self) -> None:
            self.response_calls = 0
            self.linked_response = FakeResponse(
                _hourly_url(),
                json.dumps(
                    {
                        "success": True,
                        "metaData": {"fields": ["0", "12"]},
                        "rows": [{"0": "9", "1": "20", "_s0": "Total", "_s1": "20"}],
                    }
                ),
            )
            self.linked_response.request = self  # type: ignore[attr-defined]

        async def response(self) -> FakeResponse:
            self.response_calls += 1
            return self.linked_response

    requests = [FakeRequest(), FakeRequest()]

    class PendingRequest:
        async def __aenter__(self) -> "PendingRequest":
            self.value = _resolved(requests[0])
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    async def _resolved(value: object) -> object:
        return value

    class FakePage:
        def __init__(self) -> None:
            self.request_listeners: list[object] = []

        class Card:
            def __init__(self, page: "FakePage") -> None:
                self.page = page

            @property
            def first(self) -> "FakePage.Card":
                return self

            async def click(self, *, timeout: int) -> None:
                assert timeout == 10_000
                for request in requests:
                    for listener in tuple(self.page.request_listeners):
                        assert callable(listener)
                        listener(request)

        def get_by_text(self, _text: str, *, exact: bool) -> "FakePage.Card":
            assert exact
            return self.Card(self)

        def expect_request(self, predicate: object, *, timeout: int) -> PendingRequest:
            assert callable(predicate)
            assert all(predicate(request) for request in requests)
            assert timeout == 20_000
            return PendingRequest()

        def on(self, event: str, listener: object) -> None:
            assert event == "request"
            self.request_listeners.append(listener)

        def remove_listener(self, event: str, listener: object) -> None:
            assert event == "request"
            self.request_listeners.remove(listener)

    page = FakePage()
    with pytest.raises(ValueError, match="petición horaria ambigua"):
        await scraper_module._capture_restaurant(
            page,  # type: ignore[arg-type]
            _catcher(),
            Restaurant("R001", "Central", "Central card", 1, True),
            date(2030, 1, 15),
            close_capture=_noop_close_capture,
        )
    assert [request.response_calls for request in requests] == [0, 0]
    assert page.request_listeners == []


async def test_capture_rejects_a_second_exact_request_scheduled_by_the_same_click() -> None:
    requests = [_CaptureRequest(), _CaptureRequest()]
    requests[0].linked_response.text_body = "not-json"
    requests[0].linked_response.headers = {"content-length": "8"}
    page = _CapturePage([([requests[0]], [requests[1]])])
    accepted = False
    error = ""
    try:
        await scraper_module._capture_restaurant(
            page,  # type: ignore[arg-type]
            _catcher(),
            Restaurant("R001", "Central", "Central card", 1, True),
            date(2030, 1, 15),
            close_capture=page.close,
        )
    except ValueError as exc:
        error = str(exc)
    else:
        accepted = True

    assert page.late_emitted is True
    assert accepted is False
    assert error == "petición horaria ambigua durante el clic"
    assert [request.response_calls for request in requests] == [1, 0]
    assert page.closed is True
    assert page.request_listeners == []


async def test_capture_removes_the_listener_when_no_exact_request_arrives() -> None:
    page = _CapturePage([([], [])])

    with pytest.raises(TimeoutError, match="no exact request"):
        await scraper_module._capture_restaurant(
            page,  # type: ignore[arg-type]
            _catcher(),
            Restaurant("R001", "Central", "Central card", 1, True),
            date(2030, 1, 15),
            close_capture=page.close,
        )

    assert page.closed is True
    assert page.request_listeners == []


async def test_late_request_outside_one_capture_does_not_contaminate_the_next() -> None:
    requests = [_CaptureRequest("8", "10"), _CaptureRequest("9", "20")]
    late_request = _CaptureRequest("7", "99")
    first_page = _CapturePage([([requests[0]], [])])
    second_page = _CapturePage([([requests[1]], [])])
    catcher = _catcher()

    first_day = await scraper_module._capture_restaurant(
        first_page,  # type: ignore[arg-type]
        catcher,
        Restaurant("R001", "Central", "Central card", 1, True),
        date(2030, 1, 15),
        close_capture=first_page.close,
    )
    asyncio.get_running_loop().call_soon(first_page.emit_late_request, late_request)
    await asyncio.sleep(0)
    second_day = await scraper_module._capture_restaurant(
        second_page,  # type: ignore[arg-type]
        catcher,
        Restaurant("R002", "North", "North card", 2, True),
        date(2030, 1, 15),
        close_capture=second_page.close,
    )

    assert first_day is not None
    assert second_day is not None
    assert [row.net for row in first_day.hours] == [10]
    assert [row.net for row in second_day.hours] == [20]
    assert late_request.response_calls == 0
    assert first_page.closed is True
    assert second_page.closed is True
    assert first_page.request_listeners == []
    assert second_page.request_listeners == []


async def test_context_close_cancels_a_request_scheduled_beyond_any_quiet_window() -> None:
    first_request = _CaptureRequest("8", "10")
    delayed_request = _CaptureRequest("7", "99")
    first_page = _CapturePage(
        [([first_request], [])],
        delayed_requests=[(0.06, delayed_request)],
    )
    second_request = _CaptureRequest("9", "20")
    second_page = _CapturePage([([second_request], [])])
    catcher = _catcher()

    first_day = await scraper_module._capture_restaurant(
        first_page,  # type: ignore[arg-type]
        catcher,
        Restaurant("R001", "Central", "Central card", 1, True),
        date(2030, 1, 15),
        close_capture=first_page.close,
    )
    await asyncio.sleep(0.07)
    second_day = await scraper_module._capture_restaurant(
        second_page,  # type: ignore[arg-type]
        catcher,
        Restaurant("R002", "North", "North card", 2, True),
        date(2030, 1, 15),
        close_capture=second_page.close,
    )

    assert first_day is not None
    assert second_day is not None
    assert [row.net for row in first_day.hours] == [10]
    assert [row.net for row in second_day.hours] == [20]
    assert first_page.closed is True
    assert first_page.late_emitted is False
    assert delayed_request.response_calls == 0
    assert first_page.request_listeners == []


async def test_restaurant_click_failure_is_not_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenCard:
        @property
        def first(self) -> "BrokenCard":
            return self

        async def click(self, *, timeout: int) -> None:
            raise RuntimeError(f"click failed after {timeout}")

    class FakePage:
        class PendingRequest:
            async def __aenter__(self) -> "FakePage.PendingRequest":
                return self

            async def __aexit__(self, *_exc: object) -> None:
                return None

        def get_by_text(self, _text: str, *, exact: bool) -> BrokenCard:
            assert exact
            return BrokenCard()

        def expect_request(self, _predicate: object, *, timeout: int) -> PendingRequest:
            assert timeout == 20_000
            return self.PendingRequest()

        def on(self, event: str, _listener: object) -> None:
            assert event == "request"

        def remove_listener(self, event: str, _listener: object) -> None:
            assert event == "request"

    restaurant = Restaurant("R001", "Central", "Central card", 1, True)

    with pytest.raises(RuntimeError, match="click failed"):
        await scraper_module._capture_restaurant(
            FakePage(),  # type: ignore[arg-type]
            _catcher(),
            restaurant,
            date(2026, 8, 8),
            close_capture=_noop_close_capture,
        )


def test_marker_is_the_thirteenth_column() -> None:
    assert HOURLY_FIELD_MARKER == "12"


async def test_date_picker_confirms_with_stable_button_text() -> None:
    """El id de ExtJS cambia al cruzar de mes; el texto visible no."""
    clicked: list[int] = []

    class FakeButtons:
        def filter(self, *, has_text: object) -> "FakeButtons":
            assert has_text == scraper_module._PICKER_OK_RE
            return self

        @property
        def first(self) -> "FakeButtons":
            return self

        async def click(self, *, timeout: int) -> None:
            clicked.append(timeout)

    class FakePage:
        def locator(self, selector: str) -> FakeButtons:
            assert selector == "a.x-btn"
            return FakeButtons()

    await scraper_module._click_date_picker_ok(FakePage())  # type: ignore[arg-type]

    assert clicked == [5_000]


async def test_navigation_does_not_erase_the_payload_that_it_just_triggered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catcher = _catcher()
    navigated: list[date] = []

    async def fake_goto(_page: object, target: date) -> None:
        navigated.append(target)

    monkeypatch.setattr(scraper_module, "_goto_date", fake_goto)

    await scraper_module._navigate(object(), catcher, date(2026, 8, 8))  # type: ignore[arg-type]

    assert navigated == [date(2026, 8, 8)]


async def test_date_navigation_never_logs_the_external_header(
    caplog: pytest.LogCaptureFixture,
) -> None:
    target = date(2030, 1, 15)
    external_header = "".join(("EXTERNAL-", "SITE-ID\n", "SOURCE-TOKEN"))
    headers = iter((external_header, "Today - Tue 15 Jan"))

    async def read_header() -> str:
        return next(headers)

    async def goto_date(_target: date) -> None:
        return None

    with caplog.at_level(logging.INFO, logger="restaurant_live_ops.sales_source"):
        await ensure_date(target, read_header=read_header, goto_date=goto_date)

    assert external_header not in caplog.text
    assert caplog.messages == [
        "la fuente de ventas: la pantalla no coincide; navegando a 2030-01-15"
    ]


@pytest.mark.parametrize("failure_at", ["set_default_timeout", "new_page"])
async def test_start_session_closes_context_when_initialization_fails(
    failure_at: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeContext:
        def __init__(self) -> None:
            self.close_calls = 0

        def set_default_timeout(self, timeout: int) -> None:
            assert timeout == 30_000
            if failure_at == "set_default_timeout":
                raise RuntimeError("timeout setup failed")

        async def new_page(self) -> object:
            if failure_at == "new_page":
                raise RuntimeError("page creation failed")
            return object()

        async def close(self) -> None:
            self.close_calls += 1

    context = FakeContext()

    class FakeBrowser:
        async def new_context(self, **_kwargs: object) -> FakeContext:
            return context

    async def login_must_not_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("login no debe ejecutarse tras fallar la inicialización")

    monkeypatch.setattr(scraper_module, "_login", login_must_not_run)
    settings = SalesSourceSettings(
        base_url="https://sales.example.test",
        username="u",
        password="<test-password>",
        hourly_path="/events/HandleEvent",
        hourly_query="Obj=hourly-grid&Evt=data",
        view_label="Sales view",
    )

    with pytest.raises(RuntimeError, match=r"setup failed|creation failed"):
        await scraper_module._start_session(
            FakeBrowser(),  # type: ignore[arg-type]
            settings,
        )

    assert context.close_calls == 1


@pytest.mark.parametrize("failure_at", ["endpoint", "view", "catcher", "login"])
async def test_start_session_closes_context_once_for_settings_and_login_errors(
    failure_at: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeContext:
        def __init__(self) -> None:
            self.close_calls = 0

        def set_default_timeout(self, timeout: int) -> None:
            assert timeout == 30_000

        async def new_page(self) -> object:
            return object()

        async def close(self) -> None:
            self.close_calls += 1

    context = FakeContext()

    class FakeBrowser:
        async def new_context(self, **_kwargs: object) -> FakeContext:
            return context

    async def login(_page: object, _settings: SalesSourceSettings) -> None:
        if failure_at == "login":
            raise RuntimeError("login failed")
        raise AssertionError("login no debe ejecutarse con ajustes inválidos")

    monkeypatch.setattr(scraper_module, "_login", login)
    settings = SalesSourceSettings(
        base_url="not-a-url" if failure_at == "catcher" else "https://sales.example.test",
        username="u",
        password="<test-password>",
        hourly_path=None if failure_at == "endpoint" else "/events/HandleEvent",
        hourly_query=None if failure_at == "endpoint" else "Obj=hourly-grid&Evt=data",
        view_label=None if failure_at == "view" else "Sales view",
    )
    expected_error = {
        "endpoint": "falta el endpoint horario exacto",
        "view": "falta el selector de vista",
        "catcher": "URL exacta válida",
        "login": "login failed",
    }[failure_at]

    with pytest.raises((RuntimeError, ValueError), match=expected_error):
        await scraper_module._start_session(
            FakeBrowser(),  # type: ignore[arg-type]
            settings,
        )

    assert context.close_calls == 1


async def test_each_restaurant_capture_uses_a_clean_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una petición tardía no puede cruzar de restaurante ni de fecha."""
    contexts_created = 0
    contexts_closed = 0

    class FakePage:
        def on(self, _event: str, _callback: object) -> None:
            pass

    class FakeContext:
        def set_default_timeout(self, _timeout: int) -> None:
            pass

        async def new_page(self) -> FakePage:
            return FakePage()

        async def close(self) -> None:
            nonlocal contexts_closed
            contexts_closed += 1

    class FakeBrowser:
        async def new_context(self, **_kwargs: object) -> FakeContext:
            nonlocal contexts_created
            contexts_created += 1
            return FakeContext()

        async def close(self) -> None:
            pass

    class FakeChromium:
        async def launch(self, **_kwargs: object) -> FakeBrowser:
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        async def __aenter__(self) -> "FakePlaywright":
            return self

        async def __aexit__(self, *_exc: object) -> None:
            pass

    async def noop(*_args: object, **_kwargs: object) -> None:
        pass

    async def ensure(target: date, **_kwargs: object) -> None:
        if target == date(2026, 8, 6):
            raise StaleDateError("picker bloqueado")

    async def capture(
        _page: object,
        _catcher: object,
        restaurant: Restaurant,
        target: date,
        *,
        close_capture: Callable[[], Awaitable[None]],
    ) -> object:
        await close_capture()
        return SimpleNamespace(hours=[], restaurant_id=restaurant.id, sales_date=target)

    monkeypatch.setattr(scraper_module, "async_playwright", lambda: FakePlaywright())
    monkeypatch.setattr(scraper_module, "_login", noop)
    monkeypatch.setattr(scraper_module, "_open_sales_view", noop)
    monkeypatch.setattr(scraper_module, "ensure_date", ensure)
    monkeypatch.setattr(scraper_module, "_capture_restaurant", capture)
    monkeypatch.setattr(scraper_module, "today_madrid", lambda: date(2026, 8, 8))

    results = await scraper_module.scrape_days(
        SalesSourceSettings(
            base_url="https://sales.example.test",
            username="u",
            password="<test-password>",
            hourly_path="/events/HandleEvent",
            hourly_query="Obj=hourly-grid&Evt=data",
            view_label="Sales view",
        ),
        [date(2026, 8, 6), date(2026, 8, 7)],
        restaurants=(
            Restaurant("R001", "Central", "Central card", 1, True),
            Restaurant("R002", "North", "North card", 2, False),
            Restaurant("R003", "South", "South card", 3, True),
        ),
    )

    assert contexts_created == 6
    assert contexts_closed == 6
    assert set(results[0].errors) == {"R001", "R002", "R003"}
    assert len(results[1].days) == 3


def test_picker_month_lee_el_mes_del_calendario() -> None:
    assert picker_month("March 2026") == (2026, 3)
    assert picker_month("  December 2025 ") == (2025, 12)


def test_picker_month_admite_el_mes_abreviado() -> None:
    assert picker_month("Mar 2026") == (2026, 3)


def test_picker_month_ilegible_devuelve_none() -> None:
    # Nunca se pulsa la flecha a ciegas: sin saber en qué mes estamos, se
    # aborta. Caminar el calendario sin leerlo acabaría capturando otro día.
    assert picker_month("") is None
    assert picker_month("Marzo 2026") is None


class _Navegacion:
    """Doble de la navegación: qué encabezado se ve en cada momento."""

    def __init__(self, *etiquetas: str) -> None:
        self._etiquetas = list(etiquetas)
        self.navegaciones: list[date] = []

    async def read_header(self) -> str:
        return self._etiquetas[0] if len(self._etiquetas) == 1 else self._etiquetas.pop(0)

    async def goto(self, target: date) -> None:
        self.navegaciones.append(target)


async def test_no_navega_si_la_pantalla_ya_muestra_el_dia_pedido() -> None:
    nav = _Navegacion("Today - Mon 27 Jul")
    await ensure_date(date(2026, 7, 27), read_header=nav.read_header, goto_date=nav.goto)
    assert nav.navegaciones == []


async def test_navega_a_hoy_cuando_la_fuente_ensena_ayer() -> None:
    # Una fecha inicial distinta debe corregirse antes de capturar.
    nav = _Navegacion("Yesterday - Sun 26 Jul", "Today - Mon 27 Jul")
    await ensure_date(date(2026, 7, 27), read_header=nav.read_header, goto_date=nav.goto)
    assert nav.navegaciones == [date(2026, 7, 27)]


async def test_descarta_si_despues_de_navegar_sigue_sin_ser_el_dia_pedido() -> None:
    # Se intenta una vez; si la fuente no obedece, se descarta. Jamás se estampa
    # una captura con una fecha no verificada.
    nav = _Navegacion("Yesterday - Sun 26 Jul", "Sat 25 Jul")
    with pytest.raises(StaleDateError):
        await ensure_date(date(2026, 7, 27), read_header=nav.read_header, goto_date=nav.goto)
    assert nav.navegaciones == [date(2026, 7, 27)]


async def test_un_encabezado_ilegible_tambien_se_descarta() -> None:
    nav = _Navegacion("", "")
    with pytest.raises(StaleDateError):
        await ensure_date(date(2026, 7, 27), read_header=nav.read_header, goto_date=nav.goto)
