import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from restaurant_live_ops.config import WorkforceSourceSettings
from restaurant_live_ops.pipeline import run_sales_batch_cycle, run_sales_cycle, run_workforce_cycle
from restaurant_live_ops.public_errors import SALES_PUBLIC_ERROR, WORKFORCE_PUBLIC_ERROR
from restaurant_live_ops.sales_source.date_header import StaleDateError
from restaurant_live_ops.sales_source.parser import SalesDay, parse_hourly_response
from restaurant_live_ops.sales_source.scraper import ScrapeResult
from restaurant_live_ops.workforce_source.client import WorkforceSourceClient
from restaurant_live_ops.workforce_source.projections import HourlyProjection

NOW = datetime(2026, 7, 26, 16, 20, tzinfo=UTC)
HOY = date(2026, 7, 26)
RESTAURANT_IDS = ("R001", "R002", "R003")
EXPECTED_WORKFORCE_HOURS = {restaurant_id: (14,) for restaurant_id in RESTAURANT_IDS}
SOURCE_DAY_FIXTURE = Path(__file__).parent / "fixtures" / "sales" / "source_day.json"


def _reloj(*instantes: datetime) -> Callable[[], datetime]:
    """Reloj falso que va devolviendo los instantes dados, en orden."""
    restantes = list(instantes)
    return lambda: restantes.pop(0) if len(restantes) > 1 else restantes[0]


class FakeDb:
    """Doble de la base de datos que registra lo que se le pide escribir."""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.started_at: list[datetime] = []
        self.days: list[SalesDay] = []
        self.insert_only_days: list[SalesDay] = []
        self.captured_at: list[datetime] = []
        self.day_sources: list[str] = []
        self.projections: list[tuple[str, list[HourlyProjection]]] = []
        self.stored_hours: set[str] = set()

    def restaurants_with_hours(self, sales_date: date) -> set[str]:
        return self.stored_hours

    def start_run(self, source: str, restaurant_id: str, *, started_at: datetime) -> int:
        self.runs.append(
            {
                "source": source,
                "restaurant_id": restaurant_id,
                "status": "running",
                "error": None,
            }
        )
        self.started_at.append(started_at)
        return len(self.runs)

    def finish_run(self, run_id: int, **kwargs: Any) -> None:
        self.runs[run_id - 1].update(kwargs)

    def upsert_sales_day(self, day: SalesDay, **kwargs: Any) -> int:
        self.days.append(day)
        self.captured_at.append(kwargs["captured_at"])
        self.day_sources.append(kwargs.get("source", "live"))
        return len(day.hours)

    def insert_sales_day_if_absent(self, day: SalesDay, **kwargs: Any) -> int:
        self.insert_only_days.append(day)
        self.captured_at.append(kwargs["captured_at"])
        self.day_sources.append(kwargs["source"])
        return len(day.hours)

    def upsert_projections(
        self,
        restaurant_id: str,
        sales_date: date,
        projections: list[HourlyProjection],
        **kwargs: Any,
    ) -> int:
        self.projections.append((restaurant_id, projections))
        return len(projections)


def _day(
    restaurant_id: str,
    rows: list[dict[str, Any]] | None = None,
    *,
    sales_date: date = HOY,
) -> SalesDay:
    prepared_rows = [
        dict(row)
        for row in (
            rows
            if rows is not None
            else [{"0": "14", "1": "100,00", "_s0": "Total", "_s1": "100,00"}]
        )
    ]
    if not any("_s0" in row for row in prepared_rows):
        prepared_rows.append({"_s0": "Total", "_s1": "0"})
    return parse_hourly_response(
        {
            "success": True,
            "metaData": {"fields": ["0", "12"]},
            "rows": prepared_rows,
        },
        restaurant_id=restaurant_id,
        sales_date=sales_date,
    )


async def test_batch_cycle_publishes_both_cash_days_in_isolated_restaurant_runs() -> None:
    db = FakeDb()
    ayer = HOY - timedelta(days=1)

    async def scraper() -> list[ScrapeResult]:
        return [
            ScrapeResult(
                sales_date=ayer,
                days=[_day(rid, sales_date=ayer) for rid in RESTAURANT_IDS],
            ),
            ScrapeResult(sales_date=HOY, days=[_day(rid) for rid in RESTAURANT_IDS]),
        ]

    outcome = await run_sales_batch_cycle(
        scraper,
        db,
        RESTAURANT_IDS,
        clock=_reloj(NOW),
        expected_dates=(ayer, HOY),
    )

    assert outcome.status == "ok"
    assert outcome.rows_written == 6
    assert [day.sales_date for day in db.days] == [ayer, ayer, ayer, HOY, HOY, HOY]
    assert [run["restaurant_id"] for run in db.runs] == list(RESTAURANT_IDS)
    assert [run["status"] for run in db.runs] == ["ok", "ok", "ok"]


async def test_historical_batch_is_labelled_backfill_end_to_end() -> None:
    db = FakeDb()

    async def scraper() -> list[ScrapeResult]:
        return [ScrapeResult(sales_date=HOY, days=[_day("R001")])]

    outcome = await run_sales_batch_cycle(
        scraper,
        db,
        ("R001",),
        clock=_reloj(NOW),
        source="backfill",
        run_source="sales_backfill",
        expected_dates=(HOY,),
    )

    assert outcome.status == "ok"
    assert db.runs[0]["source"] == "sales_backfill"
    assert db.day_sources == ["backfill"]


async def test_explicit_recapture_uses_insert_only_and_never_calls_live_replacement() -> None:
    db = FakeDb()

    async def scraper() -> list[ScrapeResult]:
        return [ScrapeResult(sales_date=HOY, days=[_day("R001")])]

    outcome = await run_sales_batch_cycle(
        scraper,
        db,
        ("R001",),
        clock=_reloj(NOW),
        source="backfill",
        run_source="sales_backfill",
        write_mode="insert_only",
    )

    assert outcome.status == "ok"
    assert db.days == []
    assert db.insert_only_days == [_day("R001")]


async def test_one_bad_source_day_does_not_block_the_other_one() -> None:
    db = FakeDb()
    ayer = HOY - timedelta(days=1)

    async def scraper() -> list[ScrapeResult]:
        return [
            ScrapeResult(
                sales_date=ayer,
                days=[
                    _day("R001", sales_date=ayer),
                    _day("R003", sales_date=ayer),
                ],
                errors={"R002": "no se pudo navegar al día de caja"},
            ),
            ScrapeResult(sales_date=HOY, days=[_day(rid) for rid in RESTAURANT_IDS]),
        ]

    outcome = await run_sales_batch_cycle(
        scraper,
        db,
        RESTAURANT_IDS,
        clock=_reloj(NOW),
        expected_dates=(ayer, HOY),
    )

    assert outcome.status == "error"
    assert [(day.restaurant_id, day.sales_date) for day in db.days] == [
        ("R001", ayer),
        ("R003", ayer),
        ("R001", HOY),
        ("R002", HOY),
        ("R003", HOY),
    ]
    assert db.runs[0]["status"] == "ok"
    assert db.runs[1]["status"] == "error"
    assert db.runs[1]["error"] == SALES_PUBLIC_ERROR
    assert db.runs[2]["status"] == "ok"
    assert outcome.error == SALES_PUBLIC_ERROR


async def test_successful_cycle_writes_and_closes_the_run() -> None:
    db = FakeDb()

    async def scraper() -> ScrapeResult:
        return ScrapeResult(sales_date=HOY, days=[_day(rid) for rid in RESTAURANT_IDS])

    outcome = await run_sales_cycle(scraper, db, RESTAURANT_IDS, clock=_reloj(NOW))
    assert outcome.status == "ok"
    assert outcome.rows_written == 3
    assert db.runs[0]["status"] == "ok"
    assert db.runs[0]["error"] is None


async def test_stale_date_fails_the_cycle_and_writes_nothing() -> None:
    db = FakeDb()

    async def scraper() -> ScrapeResult:
        unsafe_error = "".join(
            ("https:/", "/private.example/path?", "to", "ken=SECRET\n", "PERSON-ID-123")
        )
        raise StaleDateError(unsafe_error)

    outcome = await run_sales_cycle(scraper, db, RESTAURANT_IDS, clock=_reloj(NOW))
    assert outcome.status == "error"
    assert db.days == []
    assert db.runs[0]["error"] == SALES_PUBLIC_ERROR
    assert outcome.error == SALES_PUBLIC_ERROR


async def test_totals_mismatch_fails_the_cycle_and_that_day_is_not_written() -> None:
    # Un descuadre por encima de la tolerancia es un fallo de parseo: no se
    # publica un número que no cuadra con su propia fuente.
    db = FakeDb()
    malo = _day("R001", [{"0": "14", "1": "100,00", "_s0": "Total", "_s1": "500,00"}])
    assert malo.totals_mismatch == Decimal("-400.00")

    async def scraper() -> ScrapeResult:
        return ScrapeResult(sales_date=HOY, days=[malo])

    outcome = await run_sales_cycle(scraper, db, RESTAURANT_IDS, clock=_reloj(NOW))
    assert outcome.status == "error"
    assert db.days == []
    assert outcome.error == SALES_PUBLIC_ERROR


async def test_missing_sales_total_fails_the_cycle_and_is_not_written() -> None:
    db = FakeDb()
    valid = _day("R001")
    missing_total = replace(valid, totals=replace(valid.totals, net=None))

    async def scraper() -> ScrapeResult:
        return ScrapeResult(sales_date=HOY, days=[missing_total])

    outcome = await run_sales_cycle(scraper, db, RESTAURANT_IDS, clock=_reloj(NOW))

    assert outcome.status == "error"
    assert db.days == []
    assert outcome.error == SALES_PUBLIC_ERROR


async def test_sales_in_hours_that_have_not_happened_are_not_published() -> None:
    # Una rejilla puede traer horas futuras y aun cuadrar con sus totales.
    db = FakeDb()
    # Con su fila de totales de verdad: 100,00 + 453,16 = 553,16 contra los 553
    # que declara la fuente de ventas. Cuadra dentro de la tolerancia, así que totals_mismatch
    # no ve nada — y sin ese detalle el test pasaría por no tener totales, no
    # por cuadrar, que es una prueba distinta y más floja.
    contaminado = _day(
        "R003",
        [{"0": "14", "1": "100,00"}, {"0": "0", "1": "453,16", "_s0": "Total", "_s1": "553"}],
    )
    assert contaminado.totals.net == Decimal("553")
    assert contaminado.totals_mismatch is None  # el guard de totales no lo ve

    async def scraper() -> ScrapeResult:
        return ScrapeResult(sales_date=HOY, days=[_day("R001"), contaminado])

    outcome = await run_sales_cycle(scraper, db, RESTAURANT_IDS, clock=_reloj(NOW))
    assert [d.restaurant_id for d in db.days] == ["R001"]
    assert outcome.status == "error"
    assert outcome.error == SALES_PUBLIC_ERROR


async def test_synthetic_source_day_is_published_without_future_hours() -> None:
    fixture = json.loads(SOURCE_DAY_FIXTURE.read_text(encoding="utf-8"))
    day = parse_hourly_response(
        fixture["payload"],
        restaurant_id=fixture["restaurant_id"],
        sales_date=date.fromisoformat(fixture["sales_date"]),
    )
    db = FakeDb()
    captured_at = datetime(2030, 1, 15, 9, 30, tzinfo=UTC)

    async def scraper() -> ScrapeResult:
        return ScrapeResult(sales_date=date(2030, 1, 15), days=[day])

    outcome = await run_sales_cycle(scraper, db, (day.restaurant_id,), clock=_reloj(captured_at))
    assert outcome.status == "ok"
    assert db.days == [day]


async def test_an_ambiguous_hour_sequence_is_a_local_rejection_not_a_crash() -> None:
    db = FakeDb()
    ambiguous = _day(
        "R003",
        [
            {"0": 22},
            {"0": 0},
            {"0": 10},
            {"0": 0},
            {"0": 10},
            {"0": 0, "_s0": "Total", "_s1": "0"},
        ],
    )

    async def scraper() -> ScrapeResult:
        return ScrapeResult(sales_date=HOY, days=[_day("R001"), ambiguous])

    outcome = await run_sales_cycle(scraper, db, RESTAURANT_IDS, clock=_reloj(NOW))
    assert outcome.status == "error"
    assert [d.restaurant_id for d in db.days] == ["R001"]
    assert db.runs[0]["status"] == "ok"
    assert db.runs[2]["status"] == "error"
    assert db.runs[2]["error"] == SALES_PUBLIC_ERROR
    assert outcome.error == SALES_PUBLIC_ERROR


async def test_a_bad_restaurant_does_not_block_the_good_ones() -> None:
    db = FakeDb()
    malo = _day("R002", [{"0": "14", "1": "100,00", "_s0": "Total", "_s1": "500,00"}])

    async def scraper() -> ScrapeResult:
        return ScrapeResult(sales_date=HOY, days=[_day("R001"), malo, _day("R003")])

    outcome = await run_sales_cycle(scraper, db, RESTAURANT_IDS, clock=_reloj(NOW))
    assert [d.restaurant_id for d in db.days] == ["R001", "R003"]
    assert outcome.status == "error"
    assert outcome.error == SALES_PUBLIC_ERROR
    assert [run["status"] for run in db.runs] == ["ok", "error", "ok"]


async def test_partial_capture_is_recorded_as_error_but_keeps_good_data() -> None:
    db = FakeDb()

    async def scraper() -> ScrapeResult:
        return ScrapeResult(
            sales_date=HOY,
            days=[_day("R001"), _day("R002")],
            errors={"R003": "no se capturó payload horario"},
        )

    outcome = await run_sales_cycle(scraper, db, RESTAURANT_IDS, clock=_reloj(NOW))
    assert len(db.days) == 2  # lo bueno se guarda
    assert outcome.status == "error"  # y el fallo se ve
    assert outcome.error == SALES_PUBLIC_ERROR
    assert [run["status"] for run in db.runs] == ["ok", "ok", "error"]
    assert db.runs[2]["error"] == SALES_PUBLIC_ERROR


async def test_empty_capture_over_stored_data_is_an_error_and_writes_nothing() -> None:
    # Un día que ya tiene horas guardadas no puede volver vacío; no se escribe
    # porque reemplazaría su fila de totales por nulos.
    db = FakeDb()
    db.stored_hours = {"R001"}
    vacio = _day("R001", [])

    async def scraper() -> ScrapeResult:
        return ScrapeResult(sales_date=HOY, days=[vacio])

    outcome = await run_sales_cycle(scraper, db, RESTAURANT_IDS, clock=_reloj(NOW))
    assert outcome.status == "error"
    assert db.days == []
    assert outcome.error == SALES_PUBLIC_ERROR


async def test_empty_capture_never_replaces_a_snapshot_even_before_first_sale() -> None:
    # Sin al menos una hora no se puede distinguir una jornada realmente vacía
    # de una respuesta incompleta. El snapshot anterior se conserva siempre.
    db = FakeDb()

    async def scraper() -> ScrapeResult:
        return ScrapeResult(sales_date=HOY, days=[_day("R001", [])])

    outcome = await run_sales_cycle(scraper, db, ("R001",), clock=_reloj(NOW))
    assert outcome.status == "error"
    assert db.days == []
    assert outcome.error == SALES_PUBLIC_ERROR


async def test_live_missing_restaurant_is_an_error_and_is_not_published() -> None:
    db = FakeDb()

    async def scraper() -> list[ScrapeResult]:
        return [ScrapeResult(sales_date=HOY, days=[_day("R001"), _day("R003")])]

    outcome = await run_sales_batch_cycle(
        scraper,
        db,
        RESTAURANT_IDS,
        clock=_reloj(NOW),
        expected_dates=(HOY,),
    )

    assert outcome.status == "error"
    assert [day.restaurant_id for day in db.days] == ["R001", "R003"]
    assert db.runs[1]["status"] == "error"
    assert db.runs[1]["error"] == SALES_PUBLIC_ERROR


async def test_live_duplicate_restaurant_is_an_error_and_neither_copy_is_published() -> None:
    db = FakeDb()

    async def scraper() -> list[ScrapeResult]:
        return [
            ScrapeResult(
                sales_date=HOY,
                days=[_day("R001"), _day("R002"), _day("R002"), _day("R003")],
            )
        ]

    outcome = await run_sales_batch_cycle(
        scraper,
        db,
        RESTAURANT_IDS,
        clock=_reloj(NOW),
        expected_dates=(HOY,),
    )

    assert outcome.status == "error"
    assert [day.restaurant_id for day in db.days] == ["R001", "R003"]
    assert db.runs[1]["status"] == "error"
    assert db.runs[1]["error"] == SALES_PUBLIC_ERROR


async def test_live_contradictory_day_and_error_is_not_published() -> None:
    db = FakeDb()

    async def scraper() -> list[ScrapeResult]:
        return [
            ScrapeResult(
                sales_date=HOY,
                days=[_day("R001")],
                errors={"R001": "respuesta incompleta"},
            )
        ]

    outcome = await run_sales_batch_cycle(
        scraper,
        db,
        ("R001",),
        clock=_reloj(NOW),
        expected_dates=(HOY,),
    )

    assert outcome.status == "error"
    assert db.days == []
    assert outcome.error == SALES_PUBLIC_ERROR


async def test_live_unexpected_restaurant_is_sanitized_and_blocks_the_source_day() -> None:
    db = FakeDb()

    async def scraper() -> list[ScrapeResult]:
        return [
            ScrapeResult(
                sales_date=HOY,
                days=[_day("R001"), _day("UNKNOWN-SOURCE-ID")],
            )
        ]

    outcome = await run_sales_batch_cycle(
        scraper,
        db,
        ("R001",),
        clock=_reloj(NOW),
        expected_dates=(HOY,),
    )

    assert outcome.status == "error"
    assert db.days == []
    assert outcome.error == SALES_PUBLIC_ERROR


async def test_workforce_cycle_writes_every_restaurant() -> None:
    db = FakeDb()

    async def fetcher(restaurant_id: str) -> list[HourlyProjection]:
        return [HourlyProjection(hour=14, sales=Decimal("100"), guest_counts=Decimal("12"))]

    outcome = await run_workforce_cycle(
        fetcher,
        db,
        ("R001", "R002", "R003"),
        HOY,
        expected_hours_by_restaurant=EXPECTED_WORKFORCE_HOURS,
        clock=_reloj(NOW),
    )
    assert outcome.status == "ok"
    assert outcome.rows_written == 3
    assert [r for r, _ in db.projections] == ["R001", "R002", "R003"]
    assert [run["restaurant_id"] for run in db.runs] == list(RESTAURANT_IDS)


@pytest.mark.parametrize("received_hours", [[], [8]])
async def test_workforce_cycle_rejects_an_initial_incomplete_cohort(
    received_hours: list[int],
) -> None:
    db = FakeDb()

    async def fetcher(_restaurant_id: str) -> list[HourlyProjection]:
        return [
            HourlyProjection(hour=hour, sales=Decimal("100"), guest_counts=Decimal("12"))
            for hour in received_hours
        ]

    outcome = await run_workforce_cycle(
        fetcher,
        db,
        ("R001",),
        HOY,
        expected_hours_by_restaurant={"R001": (8, 9)},
        clock=_reloj(NOW),
    )

    assert outcome.status == "error"
    assert outcome.rows_written == 0
    assert outcome.error == WORKFORCE_PUBLIC_ERROR
    assert db.projections == []
    assert db.runs[0]["status"] == "error"
    assert db.runs[0]["error"] == WORKFORCE_PUBLIC_ERROR


async def test_workforce_cycle_keeps_going_when_one_restaurant_fails() -> None:
    db = FakeDb()

    async def fetcher(restaurant_id: str) -> list[HourlyProjection]:
        if restaurant_id == "R002":
            raise RuntimeError("503 de la fuente de personal")
        return [HourlyProjection(hour=14, sales=Decimal("100"), guest_counts=Decimal("12"))]

    outcome = await run_workforce_cycle(
        fetcher,
        db,
        ("R001", "R002", "R003"),
        HOY,
        expected_hours_by_restaurant=EXPECTED_WORKFORCE_HOURS,
        clock=_reloj(NOW),
    )
    assert [r for r, _ in db.projections] == ["R001", "R003"]
    assert outcome.status == "error"
    assert outcome.error == WORKFORCE_PUBLIC_ERROR
    assert [run["status"] for run in db.runs] == ["ok", "error", "ok"]


async def test_workforce_cycle_closes_the_run_when_the_database_rejects_the_snapshot() -> None:
    unsafe = "".join(("https:/", "/private.example/person/", "EXTERNAL-ID\nTOKEN"))

    class RejectingDb(FakeDb):
        def upsert_projections(
            self,
            restaurant_id: str,
            sales_date: date,
            projections: list[HourlyProjection],
            **kwargs: Any,
        ) -> int:
            raise RuntimeError(unsafe)

    async def fetcher(_restaurant_id: str) -> list[HourlyProjection]:
        return [HourlyProjection(hour=14, sales=Decimal("100"), guest_counts=Decimal("12"))]

    db = RejectingDb()
    outcome = await run_workforce_cycle(
        fetcher,
        db,
        ("R001",),
        HOY,
        expected_hours_by_restaurant={"R001": (14,)},
        clock=_reloj(NOW),
    )

    assert outcome.status == "error"
    assert outcome.rows_written == 0
    assert outcome.error == WORKFORCE_PUBLIC_ERROR
    assert db.runs[0]["status"] == "error"
    assert db.runs[0]["error"] == WORKFORCE_PUBLIC_ERROR
    assert "EXTERNAL-ID" not in str(db.runs[0])


async def test_workforce_cycle_persists_only_the_sanitized_external_error() -> None:
    db = FakeDb()
    settings = WorkforceSourceSettings(
        base_url="https://wfm.example.test",
        business_id="BIZ-TEST",
        username="u",
        password="<test-password>",
        api_key=None,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200)
        return httpx.Response(
            500,
            headers={"X-Request-ID": "REQUEST-SECRET-456"},
            text="BODY-SECRET-789",
        )

    async def no_sleep(_: float) -> None: ...

    client = WorkforceSourceClient(
        settings,
        transport=httpx.MockTransport(handler),
        sleep=no_sleep,
    )

    async def fetcher(_restaurant_id: str) -> list[HourlyProjection]:
        await client.get_json("/people/EMP-SECRET-123/contracts?to" + "ken=QUERY-SECRET-234")
        raise AssertionError("la petición fallida no puede devolver datos")

    try:
        outcome = await run_workforce_cycle(
            fetcher,
            db,
            ("R001",),
            HOY,
            expected_hours_by_restaurant={"R001": (14,)},
            clock=_reloj(NOW),
        )
    finally:
        await client.aclose()

    persisted = db.runs[0]["error"]
    assert outcome.status == "error"
    assert persisted == "previsión no disponible"
    assert outcome.error == WORKFORCE_PUBLIC_ERROR
    for secret in (
        "EMP-SECRET-123",
        "QUERY-SECRET-234",
        "REQUEST-SECRET-456",
        "BODY-SECRET-789",
        "https://",
    ):
        assert secret not in persisted


async def test_run_records_real_start_and_finish_times() -> None:
    # El ciclo de la fuente de ventas tarda segundos reales: si se estampa el mismo instante
    # al abrir y al cerrar, la duración registrada sería siempre 0 y no
    # serviría para saber si la cadencia de 12 minutos aguanta.
    db = FakeDb()
    fin = NOW + timedelta(seconds=17)

    async def scraper() -> ScrapeResult:
        return ScrapeResult(sales_date=HOY, days=[_day("R001")])

    await run_sales_cycle(scraper, db, ("R001",), clock=_reloj(NOW, fin))
    assert db.runs[0]["finished_at"] == fin
    assert db.runs[0]["finished_at"] - db.started_at[0] == timedelta(seconds=17)


async def test_capture_time_is_the_moment_the_capture_finished() -> None:
    db = FakeDb()
    fin = NOW + timedelta(seconds=17)

    async def scraper() -> ScrapeResult:
        return ScrapeResult(sales_date=HOY, days=[_day("R001")])

    await run_sales_cycle(scraper, db, ("R001",), clock=_reloj(NOW, fin))
    assert db.captured_at == [fin]
