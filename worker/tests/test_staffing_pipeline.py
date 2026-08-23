"""El ciclo de personal: escribe lo que llega y deja constancia de lo que no."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from restaurant_live_ops.pipeline import run_staffing_cycle
from restaurant_live_ops.public_errors import STAFFING_PUBLIC_ERROR
from restaurant_live_ops.tz import MADRID
from restaurant_live_ops.workforce_source.hourly import HourlyStaffing

NOW = datetime(2026, 7, 26, 16, 20, tzinfo=UTC)
HOY = date(2026, 7, 26)


def md(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=MADRID)


class FakeDb:
    """Doble de la base de datos que registra lo que se le pide escribir."""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.writes: list[tuple[str, date, list[HourlyStaffing]]] = []

    def start_run(self, source: str, restaurant_id: str, *, started_at: datetime) -> int:
        self.runs.append(
            {
                "source": source,
                "restaurant_id": restaurant_id,
                "status": "running",
                "error": None,
            }
        )
        return len(self.runs)

    def finish_run(self, run_id: int, **kwargs: Any) -> None:
        self.runs[run_id - 1].update(kwargs)

    def upsert_staffing(
        self,
        restaurant_id: str,
        sales_date: date,
        staffing: list[HourlyStaffing],
        **kwargs: Any,
    ) -> int:
        self.writes.append((restaurant_id, sales_date, staffing))
        return len(staffing)


def _fila(hour: int, *, clocked: int | None = 3, assigned: int = 4) -> HourlyStaffing:
    return HourlyStaffing(
        hour=hour,
        clocked_count=clocked,
        assigned_count=assigned,
        clocked_minutes=None if clocked is None else clocked * 60,
        assigned_minutes=assigned * 60,
        open_anomalies=0,
    )


async def test_successful_cycle_writes_the_three_restaurants() -> None:
    db = FakeDb()

    async def fetcher(restaurant_id: str, day: date) -> list[HourlyStaffing]:
        return [_fila(13)]

    outcome = await run_staffing_cycle(
        fetcher,
        db,
        ("R001", "R002", "R003"),
        HOY,
        expected_hours_by_restaurant={
            "R001": (13,),
            "R002": (13,),
            "R003": (13,),
        },
        clock=lambda: NOW,
    )
    assert outcome.status == "ok"
    assert [w[0] for w in db.writes] == ["R001", "R002", "R003"]
    assert db.runs[0]["source"] == "staffing"
    assert db.runs[0]["status"] == "ok"
    assert [run["restaurant_id"] for run in db.runs] == ["R001", "R002", "R003"]


@pytest.mark.parametrize("received_hours", [[], [8]])
async def test_staffing_cycle_rejects_an_initial_incomplete_cohort(
    received_hours: list[int],
) -> None:
    db = FakeDb()

    async def fetcher(_restaurant_id: str, _day: date) -> list[HourlyStaffing]:
        return [_fila(hour) for hour in received_hours]

    outcome = await run_staffing_cycle(
        fetcher,
        db,
        ("R001",),
        HOY,
        expected_hours_by_restaurant={"R001": (8, 9)},
        clock=lambda: NOW,
    )

    assert outcome.status == "error"
    assert outcome.rows_written == 0
    assert outcome.error == STAFFING_PUBLIC_ERROR
    assert db.writes == []
    assert db.runs[0]["status"] == "error"
    assert db.runs[0]["error"] == STAFFING_PUBLIC_ERROR


async def test_one_restaurant_down_does_not_take_the_others_but_marks_error() -> None:
    db = FakeDb()

    async def fetcher(restaurant_id: str, day: date) -> list[HourlyStaffing]:
        if restaurant_id == "R002":
            unsafe_error = "".join(
                ("https:/", "/private.example/person/EMP-SECRET?", "to", "ken=SECRET\nNEXT")
            )
            raise RuntimeError(unsafe_error)
        return [_fila(13)]

    outcome = await run_staffing_cycle(
        fetcher,
        db,
        ("R001", "R002", "R003"),
        HOY,
        expected_hours_by_restaurant={
            "R001": (13,),
            "R002": (13,),
            "R003": (13,),
        },
        clock=lambda: NOW,
    )
    assert outcome.status == "error"
    assert outcome.error is not None
    assert outcome.error == STAFFING_PUBLIC_ERROR
    assert db.runs[1]["error"] == STAFFING_PUBLIC_ERROR
    assert "SECRET" not in outcome.error
    assert [w[0] for w in db.writes] == ["R001", "R003"]
    assert [run["status"] for run in db.runs] == ["ok", "error", "ok"]


async def test_staffing_cycle_closes_the_run_when_the_database_rejects_the_snapshot() -> None:
    unsafe = "".join(("https:/", "/private.example/person/", "EXTERNAL-ID\nTOKEN"))

    class RejectingDb(FakeDb):
        def upsert_staffing(
            self,
            restaurant_id: str,
            sales_date: date,
            staffing: list[HourlyStaffing],
            **kwargs: Any,
        ) -> int:
            raise RuntimeError(unsafe)

    async def fetcher(_restaurant_id: str, _day: date) -> list[HourlyStaffing]:
        return [_fila(13)]

    db = RejectingDb()
    outcome = await run_staffing_cycle(
        fetcher,
        db,
        ("R001",),
        HOY,
        expected_hours_by_restaurant={"R001": (13,)},
        clock=lambda: NOW,
    )

    assert outcome.status == "error"
    assert outcome.rows_written == 0
    assert outcome.error == STAFFING_PUBLIC_ERROR
    assert db.runs[0]["status"] == "error"
    assert db.runs[0]["error"] == STAFFING_PUBLIC_ERROR
    assert "EXTERNAL-ID" not in str(db.runs[0])


async def test_a_roster_with_no_punches_at_all_is_a_dead_feed_not_an_empty_shift() -> None:
    # Si hay turnos asignados y CERO fichados en todo el día, la fuente falló.
    # Escribir ceros publicaría una plantilla vacía que no ha existido.
    db = FakeDb()

    async def fetcher(restaurant_id: str, day: date) -> list[HourlyStaffing]:
        return [_fila(13, clocked=0, assigned=6)]

    outcome = await run_staffing_cycle(
        fetcher,
        db,
        ("R001",),
        HOY,
        expected_hours_by_restaurant={"R001": (13,)},
        clock=lambda: NOW,
    )
    assert outcome.status == "error"
    assert outcome.error is not None
    assert outcome.error == STAFFING_PUBLIC_ERROR
    assert db.writes == []


async def test_a_day_with_no_rows_is_rejected_without_a_complete_initial_cohort() -> None:
    db = FakeDb()

    async def fetcher(restaurant_id: str, day: date) -> list[HourlyStaffing]:
        return []

    outcome = await run_staffing_cycle(
        fetcher,
        db,
        ("R001",),
        HOY,
        expected_hours_by_restaurant={"R001": (13,)},
        clock=lambda: NOW,
    )
    assert outcome.status == "error"
    assert outcome.error == STAFFING_PUBLIC_ERROR
    assert db.writes == []


async def test_future_hours_do_not_trigger_the_dead_feed_guard() -> None:
    # A primera hora, el cuadrante del día entero ya está y casi nadie ha
    # fichado: las horas futuras traen clocked_count nulo y no deben leerse
    # como "el feed está caído".
    db = FakeDb()

    async def fetcher(restaurant_id: str, day: date) -> list[HourlyStaffing]:
        return [
            _fila(9, clocked=2, assigned=2),
            _fila(20, clocked=None, assigned=8),
        ]

    outcome = await run_staffing_cycle(
        fetcher,
        db,
        ("R001",),
        HOY,
        expected_hours_by_restaurant={"R001": (9, 20)},
        clock=lambda: NOW,
    )
    assert outcome.status == "ok"
    assert len(db.writes) == 1


class TestTheDeadFeedGuardWaitsForLatePunches:
    """El aviso de feed caído solo mira horas que llevan un rato cerradas."""

    async def test_the_first_hour_of_the_day_is_not_a_dead_feed(self) -> None:
        # Un turno recién empezado puede no haber aparecido aún en el feed.
        db = FakeDb()

        async def fetcher(restaurant_id: str, day: date) -> list[HourlyStaffing]:
            return [_fila(8, clocked=0, assigned=3)]

        outcome = await run_staffing_cycle(
            fetcher,
            db,
            ("R003",),
            HOY,
            expected_hours_by_restaurant={"R003": (8,)},
            clock=lambda: md(2026, 7, 26, 8, 31),
        )
        assert outcome.status == "ok"
        assert len(db.writes) == 1

    async def test_a_just_closed_hour_still_waits_for_its_punches(self) -> None:
        # Una hora recién cerrada conserva la cortesía para marcajes tardíos.
        db = FakeDb()

        async def fetcher(restaurant_id: str, day: date) -> list[HourlyStaffing]:
            return [_fila(8, clocked=0, assigned=2), _fila(9, clocked=0, assigned=9)]

        outcome = await run_staffing_cycle(
            fetcher,
            db,
            ("R001",),
            HOY,
            expected_hours_by_restaurant={"R001": (8, 9)},
            clock=lambda: md(2026, 7, 26, 9, 16),
        )
        assert outcome.status == "ok"
        assert len(db.writes) == 1

    async def test_a_dead_feed_still_shows_once_the_hours_have_settled(self) -> None:
        # Las mismas filas a media mañana ya no tienen excusa: si a las 11:30
        # no ha fichado nadie en todo el día, la fuente falló.
        db = FakeDb()

        async def fetcher(restaurant_id: str, day: date) -> list[HourlyStaffing]:
            return [_fila(8, clocked=0, assigned=2), _fila(9, clocked=0, assigned=9)]

        outcome = await run_staffing_cycle(
            fetcher,
            db,
            ("R001",),
            HOY,
            expected_hours_by_restaurant={"R001": (8, 9)},
            clock=lambda: md(2026, 7, 26, 11, 30),
        )
        assert outcome.status == "error"
        assert outcome.error is not None
        assert outcome.error == STAFFING_PUBLIC_ERROR
        assert db.writes == []

    async def test_the_small_hours_are_measured_against_the_next_civil_day(self) -> None:
        # La fila 2 del día 26 cierra a las 03:00 del 27: a las 04:00 lleva una
        # hora cerrada, no veinticinco. Anclarla al día equivocado convertiría
        # cada madrugada en un feed caído.
        db = FakeDb()

        async def fetcher(restaurant_id: str, day: date) -> list[HourlyStaffing]:
            return [_fila(2, clocked=0, assigned=4)]

        outcome = await run_staffing_cycle(
            fetcher,
            db,
            ("R001",),
            HOY,
            expected_hours_by_restaurant={"R001": (2,)},
            clock=lambda: md(2026, 7, 27, 4, 0),
        )
        assert outcome.status == "ok"
        assert len(db.writes) == 1
