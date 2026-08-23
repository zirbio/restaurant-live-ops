"""Recuperación de huecos.

Una captura se guarda solo si cuadra con la fila de totales de la fuente de ventas. Un día
que no cuadra se deja como hueco y se volverá a intentar mañana: es preferible
a publicar una captura a la que le faltan horas.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from restaurant_live_ops.backfill import days_to_recapture, run_backfill_cycle
from restaurant_live_ops.public_errors import BACKFILL_PUBLIC_ERROR
from restaurant_live_ops.sales_source.parser import (
    SalesDay,
    SalesDayTotals,
    SalesHour,
    parse_hourly_response,
)
from restaurant_live_ops.sales_source.scraper import ScrapeResult

AHORA = datetime(2026, 3, 22, 2, 0, tzinfo=UTC)


class _DbFalsa:
    def __init__(self) -> None:
        self.runs: list[dict[str, str | None]] = []
        self.escritos: list[tuple[str, date]] = []
        self.con_horas: set[str] = set()
        self._id = 0

    def restaurants_with_hours(self, sales_date: date) -> set[str]:
        return self.con_horas

    def start_run(self, source: str, restaurant_id: str, *, started_at: datetime) -> int:
        self._id += 1
        self.runs.append(
            {
                "source": source,
                "restaurant_id": restaurant_id,
                "status": "running",
                "error": None,
            }
        )
        return self._id

    def finish_run(
        self,
        run_id: int,
        *,
        finished_at: datetime,
        status: str,
        rows_written: int = 0,
        error: str | None = None,
    ) -> None:
        self.runs[run_id - 1].update({"status": status, "error": error})

    def upsert_sales_day(
        self,
        day: SalesDay,
        *,
        captured_at: datetime,
        header_date: date | None,
        source: str = "live",
    ) -> int:
        assert source == "backfill"
        # El día recuperado SÍ trae verificación de encabezado: se registra.
        assert header_date == day.sales_date
        self.escritos.append((day.restaurant_id, day.sales_date))
        return len(day.hours)


def _day(rid: str, d: date, neto: str, total: str) -> SalesDay:
    return SalesDay(
        restaurant_id=rid,
        sales_date=d,
        hours=[
            SalesHour(
                hour=13,
                net=Decimal(neto),
                gross=None,
                gc=None,
                drive_through_net=None,
                drive_through_gross=None,
                drive_through_cars=None,
                kvs=None,
                r2p=None,
                oepe=None,
                delivery_net=None,
                delivery_gross=None,
                delivery_count=None,
            )
        ],
        totals=SalesDayTotals(
            net=Decimal(total),
            gross=None,
            gc=None,
            drive_through_net=None,
            drive_through_gross=None,
            drive_through_cars=None,
            kvs=None,
            r2p=None,
            oepe=None,
            delivery_net=None,
            delivery_gross=None,
            delivery_count=None,
        ),
    )


def test_days_to_recapture_agrupa_los_locales_de_un_mismo_dia() -> None:
    # Una sola visita trae todos los locales: cada día se solicita una vez.
    huecos = [
        ("R001", date(2026, 3, 20)),
        ("R003", date(2026, 3, 20)),
        ("R001", date(2026, 3, 21)),
    ]
    assert days_to_recapture(huecos) == [date(2026, 3, 20), date(2026, 3, 21)]


async def test_una_recaptura_vacia_de_un_dia_con_datos_no_se_guarda() -> None:
    # Reescribir un día bueno con una grid vacía machacaría la fila de totales
    # con nulos. Si la fuente de ventas devuelve vacío un día que tiene horas, es un fallo.
    db = _DbFalsa()
    db.con_horas = {"R001"}
    dia = date(2026, 3, 20)
    vacio = SalesDay(
        restaurant_id="R001",
        sales_date=dia,
        hours=[],
        totals=SalesDayTotals(
            net=None,
            gross=None,
            gc=None,
            drive_through_net=None,
            drive_through_gross=None,
            drive_through_cars=None,
            kvs=None,
            r2p=None,
            oepe=None,
            delivery_net=None,
            delivery_gross=None,
            delivery_count=None,
        ),
    )

    async def scraper(_d: date) -> ScrapeResult:
        return ScrapeResult(sales_date=dia, days=[vacio])

    outcome = await run_backfill_cycle([("R001", dia)], scraper, db, clock=lambda: AHORA)
    assert db.escritos == []
    assert outcome.status == "error"
    assert outcome.error == BACKFILL_PUBLIC_ERROR


async def test_guarda_el_dia_recapturado_con_su_procedencia() -> None:
    db = _DbFalsa()
    dia = date(2026, 3, 20)

    async def scraper(target: date) -> ScrapeResult:
        r = ScrapeResult(sales_date=target)
        r.days.append(_day("R001", target, "100.00", "100.00"))
        return r

    outcome = await run_backfill_cycle([("R001", dia)], scraper, db, clock=lambda: AHORA)

    assert outcome.status == "ok"
    assert db.escritos == [("R001", dia)]
    assert db.runs[0]["source"] == "sales_backfill"
    assert db.runs[0]["restaurant_id"] == "R001"


async def test_no_guarda_una_captura_que_no_cuadra() -> None:
    db = _DbFalsa()
    dia = date(2026, 3, 20)

    async def scraper(target: date) -> ScrapeResult:
        r = ScrapeResult(sales_date=target)
        r.days.append(_day("R001", target, "8172.27", "7936.00"))
        return r

    outcome = await run_backfill_cycle([("R001", dia)], scraper, db, clock=lambda: AHORA)

    assert db.escritos == []
    assert outcome.status == "error"
    assert outcome.error == BACKFILL_PUBLIC_ERROR


async def test_backfill_rejects_an_ambiguous_hour_sequence() -> None:
    db = _DbFalsa()
    dia = date(2026, 3, 20)
    ambiguous = parse_hourly_response(
        {
            "success": True,
            "rows": [
                {"0": 22},
                {"0": 0},
                {"0": 10},
                {"0": 0},
                {"0": 10},
                {"0": 0, "_s0": "Total", "_s1": "0"},
            ],
        },
        restaurant_id="R001",
        sales_date=dia,
    )

    async def scraper(target: date) -> ScrapeResult:
        return ScrapeResult(sales_date=target, days=[ambiguous])

    outcome = await run_backfill_cycle([("R001", dia)], scraper, db, clock=lambda: AHORA)

    assert outcome.status == "error"
    assert db.escritos == []
    assert outcome.error == BACKFILL_PUBLIC_ERROR


async def test_un_dia_fallido_no_tumba_a_los_demas() -> None:
    db = _DbFalsa()
    malo, bueno = date(2026, 3, 20), date(2026, 3, 21)

    async def scraper(target: date) -> ScrapeResult:
        if target == malo:
            unsafe_error = "".join(
                ("https:/", "/private.example/day?", "to", "ken=SECRET\n", "PERSON-ID-123")
            )
            raise RuntimeError(unsafe_error)
        r = ScrapeResult(sales_date=target)
        r.days.append(_day("R001", target, "100.00", "100.00"))
        return r

    outcome = await run_backfill_cycle(
        [("R001", malo), ("R001", bueno)], scraper, db, clock=lambda: AHORA
    )

    assert db.escritos == [("R001", bueno)]
    assert outcome.status == "error"
    assert outcome.error == BACKFILL_PUBLIC_ERROR
    assert db.runs[0]["error"] == BACKFILL_PUBLIC_ERROR


async def test_sin_huecos_no_abre_el_navegador() -> None:
    db = _DbFalsa()

    async def scraper(target: date) -> ScrapeResult:  # pragma: no cover - no debe llamarse
        raise AssertionError("no debería haberse abierto el navegador")

    outcome = await run_backfill_cycle([], scraper, db, clock=lambda: AHORA)

    assert outcome.status == "ok"
    assert outcome.rows_written == 0
    assert db.runs == []


async def test_backfill_keeps_each_restaurant_run_isolated() -> None:
    db = _DbFalsa()
    dia = date(2026, 3, 20)

    async def scraper(target: date) -> ScrapeResult:
        return ScrapeResult(
            sales_date=target,
            days=[_day("R001", target, "100.00", "100.00")],
            errors={"R002": "respuesta incompleta"},
        )

    outcome = await run_backfill_cycle(
        [("R001", dia), ("R002", dia)], scraper, db, clock=lambda: AHORA
    )

    assert outcome.status == "error"
    assert [run["restaurant_id"] for run in db.runs] == ["R001", "R002"]
    assert [run["status"] for run in db.runs] == ["ok", "error"]


async def test_backfill_marks_an_omitted_requested_pair_as_error() -> None:
    db = _DbFalsa()
    dia = date(2026, 3, 20)

    async def scraper(target: date) -> ScrapeResult:
        return ScrapeResult(
            sales_date=target,
            days=[_day("R001", target, "100.00", "100.00")],
        )

    outcome = await run_backfill_cycle(
        [("R001", dia), ("R002", dia)],
        scraper,
        db,
        clock=lambda: AHORA,
        configured_restaurant_ids=("R001", "R002", "R003"),
    )

    assert outcome.status == "error"
    assert db.escritos == [("R001", dia)]
    assert db.runs[1]["status"] == "error"
    assert db.runs[1]["error"] == BACKFILL_PUBLIC_ERROR


async def test_backfill_rejects_both_copies_of_a_duplicated_requested_pair() -> None:
    db = _DbFalsa()
    dia = date(2026, 3, 20)

    async def scraper(target: date) -> ScrapeResult:
        duplicate = _day("R001", target, "100.00", "100.00")
        return ScrapeResult(sales_date=target, days=[duplicate, duplicate])

    outcome = await run_backfill_cycle(
        [("R001", dia)],
        scraper,
        db,
        clock=lambda: AHORA,
        configured_restaurant_ids=("R001", "R002", "R003"),
    )

    assert outcome.status == "error"
    assert db.escritos == []
    assert outcome.error == BACKFILL_PUBLIC_ERROR
