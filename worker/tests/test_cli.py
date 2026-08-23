"""El ciclo de ventas cubre los dos días de caja que pueden seguir vivos."""

import logging
import sys
from datetime import UTC, date, datetime

import httpx
import pytest

import restaurant_live_ops.cli as cli_module
from restaurant_live_ops.cli import (
    cycle_targets,
    recapture_batches,
    sales_cycle_targets,
)
from restaurant_live_ops.config import DbSettings, SalesSourceSettings, WorkforceSourceSettings
from restaurant_live_ops.pipeline import CycleOutcome
from restaurant_live_ops.restaurants import Restaurant
from restaurant_live_ops.workforce_source.client import ExternalSourceError, WorkforceSourceClient


def test_overnight_sales_captures_both_source_days() -> None:
    # Durante el relevo, cada restaurante puede estar en una fecha distinta.
    madrugada = datetime(2026, 7, 28, 1, 0, tzinfo=UTC)
    assert sales_cycle_targets(madrugada) == [date(2026, 7, 27), date(2026, 7, 28)]


def test_noon_still_seals_the_previous_sales_source_day() -> None:
    # La ventana de sellado conserva el día anterior hasta el límite común.
    mediodia = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
    assert sales_cycle_targets(mediodia) == [date(2026, 7, 27), date(2026, 7, 28)]


def test_after_the_seal_window_sales_only_captures_today() -> None:
    # 11:00 UTC = 13:00 en Madrid: los dos días de caja ya quedaron sellados.
    assert sales_cycle_targets(datetime(2026, 7, 28, 11, 0, tzinfo=UTC)) == [date(2026, 7, 28)]


def test_explicit_recapture_is_split_into_bounded_browser_sessions() -> None:
    assert recapture_batches(date(2026, 7, 1), date(2026, 7, 9), size=4) == [
        [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 4)],
        [date(2026, 7, 5), date(2026, 7, 6), date(2026, 7, 7), date(2026, 7, 8)],
        [date(2026, 7, 9)],
    ]


async def test_explicit_recapture_routes_every_batch_through_insert_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def record_cycle(
        _scraper: object,
        _db: object,
        _restaurant_ids: tuple[str, ...],
        **kwargs: object,
    ) -> CycleOutcome:
        calls.append(kwargs)
        return CycleOutcome(status="ok", rows_written=0)

    monkeypatch.setattr(
        DbSettings,
        "from_env",
        classmethod(lambda _cls: DbSettings(url="postgresql://local.invalid")),
    )
    monkeypatch.setattr(
        SalesSourceSettings,
        "from_env",
        classmethod(
            lambda _cls: SalesSourceSettings(
                base_url="https://sales.invalid",
                username="synthetic-user",
                password="<test-password>",
            )
        ),
    )
    monkeypatch.setattr(cli_module, "Database", lambda _url: object())
    monkeypatch.setattr(
        cli_module,
        "restaurants_from_env",
        lambda: (
            Restaurant(
                id="R001",
                name="Centro",
                source_site="SITE-TEST-001",
                display_order=1,
                has_drive_through=True,
            ),
        ),
    )
    monkeypatch.setattr(cli_module, "run_sales_batch_cycle", record_cycle)
    monkeypatch.setattr(cli_module, "today_madrid", lambda: date(2026, 8, 22))

    result = await cli_module._recapture_sales(date(2026, 8, 19), date(2026, 8, 20))

    assert result == 0
    assert calls == [
        {
            "source": "backfill",
            "run_source": "sales_backfill",
            "write_mode": "insert_only",
            "expected_dates": (date(2026, 8, 19), date(2026, 8, 20)),
        }
    ]


def test_overnight_staffing_follows_the_live_business_day() -> None:
    # A las 03:00 de Madrid los fichajes que entran son del día de ayer.
    assert cycle_targets(datetime(2026, 7, 28, 1, 0, tzinfo=UTC)) == [date(2026, 7, 27)]


def test_morning_staffing_also_seals_yesterday() -> None:
    # Los primeros ciclos tras el corte repasan el día recién cerrado: el
    # último ciclo de la madrugada se quedó a minutos del cierre y la cola
    # final de fichajes quedaría sin recoger.
    madrugadores = cycle_targets(datetime(2026, 7, 28, 5, 0, tzinfo=UTC))  # 07:00 Madrid
    assert madrugadores == [date(2026, 7, 28), date(2026, 7, 27)]


def test_midday_staffing_only_updates_today() -> None:
    assert cycle_targets(datetime(2026, 7, 28, 10, 0, tzinfo=UTC)) == [date(2026, 7, 28)]


def test_worker_logging_hides_http_request_details_but_keeps_own_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_path = "/people/SENSITIVE-PERSON-ID/contracts?access_hint=SENSITIVE-QUERY-VALUE"

    async def no_sleep(_: float) -> None: ...

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/importer/login":
            return httpx.Response(200)
        return httpx.Response(500)

    async def failing_workforce() -> int:
        client = WorkforceSourceClient(
            WorkforceSourceSettings(
                base_url="https://workforce.invalid",
                business_id="business-placeholder",
                username="worker-placeholder",
                password="<test-password>",
                api_key=None,
            ),
            transport=httpx.MockTransport(handler),
            sleep=no_sleep,
        )
        try:
            await client.get_json(sensitive_path)
        except ExternalSourceError as exc:
            return cli_module._report(
                "workforce",
                CycleOutcome(status="error", rows_written=0, error=str(exc)),
            )
        finally:
            await client.aclose()
        raise AssertionError("la petición debía fallar")

    prior_levels = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(cli_module, "_workforce", failing_workforce)
    monkeypatch.setattr(sys, "argv", ["restaurant-live-ops-worker", "workforce"])

    try:
        assert cli_module.main() == 1
    finally:
        for name, level in prior_levels.items():
            logging.getLogger(name).setLevel(level)

    log_output = caplog.text
    own_error = "ciclo workforce con problemas: previsión no disponible"
    assert own_error in log_output
    assert "https://workforce.invalid" not in log_output
    assert "SENSITIVE-PERSON-ID" not in log_output
    assert "access_hint" not in log_output
    assert "SENSITIVE-QUERY-VALUE" not in log_output
