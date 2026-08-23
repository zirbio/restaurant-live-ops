"""Captura de la rejilla horaria de la fuente de ventas con Playwright.

La fuente de ventas sirve cada tabla por un endpoint de eventos; las
stores responden a ``Evt=data`` con JSON limpio. En vez de raspar el DOM
renderizado (dos minutos por restaurante), se conduce la interfaz lo justo
para que el servidor recargue cada grid y se **intercepta la respuesta**.
Un solo login sirve para el lote de restaurantes. Las esperas son por evento
de red, nunca por ``sleep`` fijo.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlsplit

from playwright.async_api import Browser, BrowserContext, Page, Request, async_playwright

from restaurant_live_ops.config import SalesSourceSettings
from restaurant_live_ops.restaurants import Restaurant, restaurants_from_env
from restaurant_live_ops.sales_source.date_header import (
    DATE_HEADER_JS,
    StaleDateError,
    assert_verifiable,
    matches_date,
)
from restaurant_live_ops.sales_source.parser import SalesDay, parse_hourly_response
from restaurant_live_ops.tz import today_madrid

logger = logging.getLogger("restaurant_live_ops.sales_source")


def _utc_now() -> datetime:
    """Instante actual en UTC: mismo patrón que ``pipeline.py`` y ``backfill.py``."""
    return datetime.now(UTC)


# La grid horaria tiene 13 columnas; las de la pantalla Start, 9.
HOURLY_FIELD_MARKER = "12"
MAX_SALES_RESPONSE_BYTES = 1_048_576
MAX_SALES_ROWS = 96

# la fuente de ventas degrada su HTML con motores antiguos: hace falta un Chrome reciente.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

# --disable-dev-shm-usage es obligatorio en contenedor: /dev/shm son 64 MB por
# defecto y las grids grandes de ExtJS lo desbordan, dejando la página colgada.
CHROMIUM_ARGS = ["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"]

# Selectores del calendario de la fuente. El de apertura combina id de ExtJS y
# clase; el botón de confirmación se identifica por texto porque ExtJS cambia
# su id al cruzar de mes.
DATE_PICKER_OPEN = "#O5EB_id, i.fas.fa-angle-down"
DATE_PICKER_OK = "a.x-btn"
PICKER_MONTH = ".x-datepicker-month button, .x-datepicker-month"
_PICKER_OK_RE = re.compile(r"^(?:OK|Aceptar)$", re.IGNORECASE)

_PICKER_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_PICKER_RE = re.compile(r"([A-Za-z]+)\s+(\d{4})")


def picker_month(text: str) -> tuple[int, int] | None:
    """Lee el mes que muestra el calendario: ``"March 2026"`` → ``(2026, 3)``."""
    m = _PICKER_RE.search(text or "")
    if m is None:
        return None
    mes = _PICKER_MONTHS.get(m.group(1).lower())
    return None if mes is None else (int(m.group(2)), mes)


class _UrlEvent(Protocol):
    @property
    def url(self) -> str: ...


class _Response(_UrlEvent, Protocol):
    @property
    def headers(self) -> Mapping[str, str] | None: ...

    async def body(self) -> bytes: ...


class _Request(_UrlEvent, Protocol):
    async def response(self) -> _Response | None: ...


@dataclass(frozen=True)
class _CaptureSelection:
    restaurant_id: str
    generation: int


class HourlyCatcher:
    """Valida una única respuesta ligada a la selección activa."""

    def __init__(self, endpoint_url: str) -> None:
        endpoint = self._url_key(endpoint_url)
        if endpoint is None:
            raise ValueError("el endpoint horario no es una URL exacta válida")
        self._endpoint = endpoint
        self._generation = 0
        self._active: _CaptureSelection | None = None

    @staticmethod
    def _url_key(url: str) -> tuple[str, str, int | None, str, tuple[tuple[str, str], ...]] | None:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            return None
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or not parsed.path
            or not parsed.query
        ):
            return None
        query = tuple(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
        return (parsed.scheme, parsed.hostname.casefold(), port, parsed.path, query)

    def matches(self, event: _UrlEvent) -> bool:
        return self._url_key(event.url) == self._endpoint

    def begin_capture(self, restaurant_id: str) -> _CaptureSelection:
        self._generation += 1
        selection = _CaptureSelection(restaurant_id=restaurant_id, generation=self._generation)
        self._active = selection
        return selection

    async def _read_body(self, response: _Response, selection: _CaptureSelection) -> bytes:
        if selection != self._active:
            raise ValueError("respuesta horaria ajena a la selección actual")
        if not self.matches(response):
            raise ValueError("respuesta horaria no correlacionada")

        headers = {key.casefold(): value for key, value in (response.headers or {}).items()}
        declared_length = headers.get("content-length")
        if declared_length is None or "transfer-encoding" in headers:
            raise ValueError("respuesta horaria sin longitud fiable")
        try:
            length = int(declared_length)
        except ValueError:
            raise ValueError("respuesta horaria con longitud inválida") from None
        if length < 0 or length > MAX_SALES_RESPONSE_BYTES:
            raise ValueError("respuesta horaria supera el límite de bytes")

        body = await response.body()
        if len(body) != length:
            raise ValueError("respuesta horaria con longitud inconsistente")
        return body

    def _parse_body(self, body: bytes, selection: _CaptureSelection) -> dict[str, Any]:
        if selection != self._active:
            raise ValueError("respuesta horaria ajena a la selección actual")
        self._active = None
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("respuesta horaria inválida") from None
        if not isinstance(data, dict):
            raise ValueError("respuesta horaria inválida")
        fields = data.get("metaData", {}).get("fields", [])
        rows = data.get("rows")
        if (
            not isinstance(fields, list)
            or HOURLY_FIELD_MARKER not in fields
            or data.get("success") is not True
            or not isinstance(rows, list)
        ):
            raise ValueError("respuesta horaria inválida")
        if len(rows) > MAX_SALES_ROWS:
            raise ValueError("respuesta horaria supera el límite de filas")
        return data

    async def capture(self, response: _Response, selection: _CaptureSelection) -> dict[str, Any]:
        body = await self._read_body(response, selection)
        return self._parse_body(body, selection)


@dataclass
class _LiveSession:
    """Contexto aislado que se puede reemplazar tras una navegación rota."""

    context: BrowserContext
    page: Page
    catcher: HourlyCatcher

    async def open_sales_view(self, label: str) -> None:
        await _open_sales_view(self.page, label)

    async def close(self) -> None:
        await self.context.close()


@dataclass
class ScrapeResult:
    sales_date: date
    days: list[SalesDay] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


class SalesSourceAuthError(RuntimeError):
    """El login en la fuente de ventas falló."""


async def _login(page: Page, settings: SalesSourceSettings) -> None:
    await page.goto(settings.base_url, wait_until="domcontentloaded")
    await page.get_by_placeholder("Username").fill(settings.username, timeout=15_000)
    await page.get_by_placeholder("Password").fill(settings.password)
    await page.get_by_role("button", name="Login").click()
    try:
        await page.locator("i.far.fa-thumbs-up").first.wait_for(timeout=20_000)
    except Exception as exc:
        raise SalesSourceAuthError("el login de la fuente de ventas no llegó al panel") from exc


async def _open_sales_view(page: Page, label: str) -> None:
    try:
        await page.get_by_text(label, exact=True).click(timeout=8_000)
    except Exception:
        # El label puede no ser clicable: se usa el icono hermano anterior.
        await (
            page.get_by_text(label, exact=True)
            .locator("xpath=preceding-sibling::*[1]")
            .click(timeout=8_000)
        )


async def _start_session(browser: Browser, settings: SalesSourceSettings) -> _LiveSession:
    """Abre un contexto limpio y lo cierra ante cualquier fallo de inicialización."""
    context = await browser.new_context(
        user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}
    )
    try:
        context.set_default_timeout(30_000)
        page = await context.new_page()
        if settings.hourly_endpoint_url is None:
            raise ValueError("falta el endpoint horario exacto de la fuente de ventas")
        if settings.view_label is None:
            raise ValueError("falta el selector de vista de la fuente de ventas")
        catcher = HourlyCatcher(settings.hourly_endpoint_url)
        await _login(page, settings)
    except Exception:
        await context.close()
        raise
    return _LiveSession(context, page, catcher)


async def _read_header(page: Page) -> str:
    return str(await page.evaluate(DATE_HEADER_JS) or "")


async def _capture_restaurant(
    page: Page,
    catcher: HourlyCatcher,
    restaurant: Restaurant,
    sales_date: date,
    *,
    close_capture: Callable[[], Awaitable[None]],
) -> SalesDay | None:
    """Atribuye una única petición y cierra su contexto antes de publicarla.

    El contexto pertenece solo a este restaurante y fecha. El listener sigue
    activo hasta cerrarlo: una petición adicional ya emitida se observa y una
    futura queda cancelada sin poder cruzar a la captura siguiente.
    """
    selection = catcher.begin_capture(restaurant.id)
    card = page.get_by_text(restaurant.source_site, exact=True).first
    candidates: list[Request] = []
    request: Request | None = None
    body: bytes | None = None

    def record_candidate(request: Request) -> None:
        if catcher.matches(request):
            candidates.append(request)

    page.on("request", record_candidate)
    try:
        async with page.expect_request(
            lambda request: catcher.matches(request), timeout=20_000
        ) as request_info:
            await card.click(timeout=10_000)
        request = await request_info.value
        if len(candidates) != 1 or candidates[0] is not request:
            raise ValueError("petición horaria ambigua durante el clic")
        response = await request.response()
        if response is None or getattr(response, "request", None) is not request:
            raise ValueError("la petición horaria no tiene una respuesta inequívoca")
        body = await catcher._read_body(response, selection)
    finally:
        try:
            await close_capture()
        finally:
            page.remove_listener("request", record_candidate)

    if request is None or len(candidates) != 1 or candidates[0] is not request:
        raise ValueError("petición horaria ambigua durante el clic")
    if body is None:
        raise ValueError("respuesta horaria inválida")
    payload = catcher._parse_body(body, selection)
    return parse_hourly_response(payload, restaurant_id=restaurant.id, sales_date=sales_date)


async def ensure_date(
    target: date,
    *,
    read_header: Callable[[], Awaitable[str]],
    goto_date: Callable[[date], Awaitable[None]],
) -> None:
    """Deja la fuente en ``target``, verificado, o lanza ``StaleDateError``.

    La fuente puede abrir en una fecha distinta de la solicitada. Si lo
    que enseña no es el día pedido, se navega a él y se vuelve a leer el
    encabezado. Se intenta **una vez**: si sigue sin coincidir, se descarta.

        Sin este reintento, una fecha inicial distinta bloquearía una captura
        válida del día objetivo.
    """
    etiqueta = await read_header()
    if matches_date(etiqueta, target):
        return

    logger.info("la fuente de ventas: la pantalla no coincide; navegando a %s", target)
    await goto_date(target)

    etiqueta = await read_header()
    if not matches_date(etiqueta, target):
        raise StaleDateError("la fuente mantiene una fecha distinta incluso tras navegar")


async def _goto_date(page: Page, target: date) -> None:
    """Posiciona la fuente en ``target`` con el calendario.

    Nunca se pulsa la flecha a ciegas: si el mes no se puede leer, se aborta.
    Caminar el calendario sin saber dónde estamos acabaría capturando otro día
    y estampándolo con la fecha pedida, que es justo el fallo que hay que
    evitar.
    """
    await page.locator(DATE_PICKER_OPEN).first.click(timeout=10_000)
    objetivo = (target.year, target.month)

    for _ in range(24):
        texto = await page.locator(PICKER_MONTH).first.inner_text(timeout=5_000)
        actual = picker_month(texto)
        if actual is None:
            raise StaleDateError("no se pudo leer el mes del calendario de la fuente")
        if actual == objetivo:
            break
        flecha = ".x-datepicker-prev" if objetivo < actual else ".x-datepicker-next"
        await page.locator(flecha).first.click(timeout=5_000)
    else:
        raise StaleDateError(f"el calendario no llegó a {target.isoformat()} en 24 pasos")

    celda = page.locator("td.x-datepicker-active").filter(has_text=re.compile(rf"^{target.day}$"))
    await celda.first.click(timeout=5_000)
    await _click_date_picker_ok(page)


async def _click_date_picker_ok(page: Page) -> None:
    """Confirma por texto: ExtJS renumera el id del botón al cambiar de mes."""
    await page.locator(DATE_PICKER_OK).filter(has_text=_PICKER_OK_RE).first.click(timeout=5_000)


async def _navigate(page: Page, catcher: HourlyCatcher, target: date) -> None:
    """Navega a ``target`` y espera a que llegue la grid nueva."""
    del catcher
    await _goto_date(page, target)


async def _capture_isolated_restaurant(
    browser: Browser,
    settings: SalesSourceSettings,
    view_label: str,
    restaurant: Restaurant,
    target: date,
) -> SalesDay | None:
    """Ejecuta una sola selección dentro de un contexto desechable."""
    session = await _start_session(browser, settings)
    closed = False

    async def close_capture() -> None:
        nonlocal closed
        if closed:
            return
        await session.close()
        closed = True

    try:
        await session.open_sales_view(view_label)
        await ensure_date(
            target,
            read_header=lambda: _read_header(session.page),
            goto_date=lambda day: _navigate(session.page, session.catcher, day),
        )
        return await _capture_restaurant(
            session.page,
            session.catcher,
            restaurant,
            target,
            close_capture=close_capture,
        )
    finally:
        await close_capture()


async def scrape_days(
    settings: SalesSourceSettings,
    targets: Sequence[date],
    *,
    headless: bool = True,
    restaurants: Sequence[Restaurant] | None = None,
) -> list[ScrapeResult]:
    """Captura varias fechas con un navegador y un contexto por selección.

    Cada restaurante y fecha se autentica en un contexto desechable. Esta
    frontera impide atribuir a la captura siguiente una petición tardía de la
    anterior.
    """
    if not targets:
        raise ValueError("hace falta al menos una fecha la fuente de ventas")
    if len(set(targets)) != len(targets):
        raise ValueError("las fechas la fuente de ventas objetivo no pueden repetirse")
    view_label = settings.view_label
    if view_label is None:
        raise ValueError("falta el selector de vista de la fuente de ventas")
    if settings.hourly_endpoint_url is None:
        raise ValueError("falta el endpoint horario exacto de la fuente de ventas")
    restaurant_config = tuple(restaurants) if restaurants is not None else restaurants_from_env()

    hoy = today_madrid()
    for target in targets:
        # Antes de abrir el navegador: si el encabezado no puede verificar el
        # día, no hay captura que valga.
        assert_verifiable(target, hoy)

    results = [ScrapeResult(sales_date=target) for target in targets]

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, args=CHROMIUM_ARGS)

        try:
            for result in results:
                target = result.sales_date
                for restaurant in restaurant_config:
                    try:
                        day = await _capture_isolated_restaurant(
                            browser,
                            settings,
                            view_label,
                            restaurant,
                            target,
                        )
                    except SalesSourceAuthError:
                        raise
                    except Exception:
                        reason = "captura de ventas no disponible"
                        result.errors[restaurant.id] = reason
                        logger.error(
                            "la fuente de ventas: captura inválida para %s el %s: %s",
                            restaurant.id,
                            target,
                            reason,
                        )
                        continue
                    if day is None:
                        result.errors[restaurant.id] = "no se capturó payload horario"
                        logger.warning(
                            "fuente de ventas: sin datos para %s el %s",
                            restaurant.id,
                            target,
                        )
                        continue
                    result.days.append(day)
                    logger.info(
                        "la fuente de ventas: capturado %s el %s (%d horas)",
                        restaurant.id,
                        target,
                        len(day.hours),
                    )
        finally:
            await browser.close()

    return results


async def scrape_day(
    settings: SalesSourceSettings,
    target: date,
    *,
    headless: bool = True,
    restaurants: Sequence[Restaurant] | None = None,
) -> ScrapeResult:
    """Captura una fecha pasada, manteniendo la API del backfill."""
    return (
        await scrape_days(
            settings,
            [target],
            headless=headless,
            restaurants=restaurants,
        )
    )[0]


async def scrape_today(settings: SalesSourceSettings, *, headless: bool = True) -> ScrapeResult:
    """Captura hoy, manteniendo la API de las llamadas existentes."""
    return (await scrape_days(settings, [today_madrid()], headless=headless))[0]
