"""Integración opt-in contra la base Supabase local recién reseteada."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest

from restaurant_live_ops.db import Database, IncompleteWorkforceSnapshotError
from restaurant_live_ops.sales_source.parser import SalesDay, SalesDayTotals, SalesHour
from restaurant_live_ops.workforce_source.hourly import HourlyStaffing
from restaurant_live_ops.workforce_source.projections import HourlyProjection

DB_URL = os.environ.get("LOCAL_SUPABASE_DB_URL")
SOURCE_DATE = date(2035, 1, 2)
DST_PRIOR_SOURCE_DATE = date(2035, 10, 27)
DST_WINNER_SOURCE_DATE = date(2035, 10, 28)
WORKFORCE_DATE = date(2035, 2, 4)


def _day(hours: list[tuple[int, str]], *, source_date: date = SOURCE_DATE) -> SalesDay:
    rows = [
        SalesHour(
            hour=hour,
            net=Decimal(net),
            gross=None,
            gc=1,
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
        for hour, net in hours
    ]
    total = sum((row.net or Decimal(0) for row in rows), Decimal(0))
    return SalesDay(
        restaurant_id="R001",
        sales_date=source_date,
        hours=rows,
        totals=SalesDayTotals(
            net=total,
            gross=None,
            gc=len(rows),
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


@pytest.mark.skipif(DB_URL is None, reason="requiere LOCAL_SUPABASE_DB_URL")
def test_workforce_snapshot_rejects_partial_refresh_without_any_write() -> None:
    assert DB_URL is not None
    database = Database(DB_URL)
    first_capture = datetime(2035, 2, 4, 8, 0, tzinfo=UTC)
    complete_capture = datetime(2035, 2, 4, 9, 0, tzinfo=UTC)

    def projections(first: str, second: str) -> list[HourlyProjection]:
        return [
            HourlyProjection(hour=8, sales=Decimal(first), guest_counts=Decimal("1")),
            HourlyProjection(hour=9, sales=Decimal(second), guest_counts=Decimal("2")),
        ]

    def staffing(first: int, second: int) -> list[HourlyStaffing]:
        return [
            HourlyStaffing(
                hour=8,
                clocked_count=first,
                assigned_count=first,
                clocked_minutes=first * 60,
                assigned_minutes=first * 60,
                open_anomalies=0,
            ),
            HourlyStaffing(
                hour=9,
                clocked_count=second,
                assigned_count=second,
                clocked_minutes=second * 60,
                assigned_minutes=second * 60,
                open_anomalies=0,
            ),
        ]

    def cleanup() -> None:
        with psycopg.connect(DB_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                "delete from workforce_projection_hourly "
                "where restaurant_id = 'R001' and sales_date = %s",
                (WORKFORCE_DATE,),
            )
            cursor.execute(
                "delete from workforce_staffing_hourly "
                "where restaurant_id = 'R001' and sales_date = %s",
                (WORKFORCE_DATE,),
            )

    cleanup()
    try:
        with pytest.raises(IncompleteWorkforceSnapshotError):
            database.upsert_projections(
                "R001",
                WORKFORCE_DATE,
                [],
                fetched_at=first_capture,
                expected_hours=(8, 9),
            )
        with pytest.raises(IncompleteWorkforceSnapshotError):
            database.upsert_staffing(
                "R001",
                WORKFORCE_DATE,
                staffing(1, 2)[:1],
                fetched_at=first_capture,
                expected_hours=(8, 9),
            )

        with psycopg.connect(DB_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                "select count(*) from workforce_projection_hourly "
                "where restaurant_id = 'R001' and sales_date = %s",
                (WORKFORCE_DATE,),
            )
            assert cursor.fetchone() == (0,)
            cursor.execute(
                "select count(*) from workforce_staffing_hourly "
                "where restaurant_id = 'R001' and sales_date = %s",
                (WORKFORCE_DATE,),
            )
            assert cursor.fetchone() == (0,)

        assert (
            database.upsert_projections(
                "R001",
                WORKFORCE_DATE,
                projections("10", "20"),
                fetched_at=first_capture,
                expected_hours=(8, 9),
            )
            == 2
        )
        assert (
            database.upsert_staffing(
                "R001",
                WORKFORCE_DATE,
                staffing(1, 2),
                fetched_at=first_capture,
                expected_hours=(8, 9),
            )
            == 2
        )

        with pytest.raises(IncompleteWorkforceSnapshotError):
            database.upsert_projections(
                "R001",
                WORKFORCE_DATE,
                projections("99", "20")[:1],
                fetched_at=complete_capture,
                expected_hours=(8, 9),
            )
        with pytest.raises(IncompleteWorkforceSnapshotError):
            database.upsert_staffing(
                "R001",
                WORKFORCE_DATE,
                staffing(9, 2)[:1],
                fetched_at=complete_capture,
                expected_hours=(8, 9),
            )

        with psycopg.connect(DB_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                "select hour, sales, fetched_at from workforce_projection_hourly "
                "where restaurant_id = 'R001' and sales_date = %s order by hour",
                (WORKFORCE_DATE,),
            )
            assert cursor.fetchall() == [
                (8, Decimal("10"), first_capture),
                (9, Decimal("20"), first_capture),
            ]
            cursor.execute(
                "select hour, clocked_count, fetched_at from workforce_staffing_hourly "
                "where restaurant_id = 'R001' and sales_date = %s order by hour",
                (WORKFORCE_DATE,),
            )
            assert cursor.fetchall() == [(8, 1, first_capture), (9, 2, first_capture)]

        assert (
            database.upsert_projections(
                "R001",
                WORKFORCE_DATE,
                projections("30", "40"),
                fetched_at=complete_capture,
                expected_hours=(8, 9),
            )
            == 2
        )
        assert (
            database.upsert_staffing(
                "R001",
                WORKFORCE_DATE,
                staffing(3, 4),
                fetched_at=complete_capture,
                expected_hours=(8, 9),
            )
            == 2
        )
    finally:
        cleanup()


@pytest.mark.skipif(DB_URL is None, reason="requiere LOCAL_SUPABASE_DB_URL")
def test_snapshot_reconciliation_empty_guard_and_recapture_are_atomic() -> None:
    assert DB_URL is not None
    database = Database(DB_URL)
    captured = datetime(2035, 1, 2, 12, 0, tzinfo=UTC)

    def cleanup() -> None:
        with psycopg.connect(DB_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                "delete from sales_daily_totals where restaurant_id = 'R001' and sales_date = %s",
                (SOURCE_DATE,),
            )
            cursor.execute(
                "delete from sales_hourly where restaurant_id = 'R001' and source_date = %s",
                (SOURCE_DATE,),
            )

    cleanup()
    try:
        assert (
            database.upsert_sales_day(
                _day([(10, "10.00"), (11, "20.00")]),
                captured_at=captured,
                header_date=SOURCE_DATE,
            )
            == 2
        )
        assert (
            database.upsert_sales_day(
                _day([(10, "15.00")]),
                captured_at=captured,
                header_date=SOURCE_DATE,
            )
            == 1
        )

        empty = _day([])
        assert (
            database.upsert_sales_day(
                empty,
                captured_at=captured,
                header_date=SOURCE_DATE,
            )
            == 0
        )
        assert (
            database.insert_sales_day_if_absent(
                _day([(12, "999.00")]),
                captured_at=captured,
                source="backfill",
            )
            == 0
        )

        with psycopg.connect(DB_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                "select hour, net, source from sales_hourly "
                "where restaurant_id = 'R001' and source_date = %s order by hour",
                (SOURCE_DATE,),
            )
            assert cursor.fetchall() == [(10, Decimal("15.00"), "live")]
            cursor.execute(
                "select net, hourly_net_sum, gc, source, quality "
                "from sales_daily_totals "
                "where restaurant_id = 'R001' and sales_date = %s",
                (SOURCE_DATE,),
            )
            assert cursor.fetchone() == (
                Decimal("15.00"),
                Decimal("15.00"),
                1,
                "live",
                "clean",
            )
    finally:
        cleanup()


@pytest.mark.skipif(DB_URL is None, reason="requiere LOCAL_SUPABASE_DB_URL")
def test_daily_totals_use_one_effective_physical_occurrence_and_restore_fallback() -> None:
    """Dos snapshots pueden contener el mismo instante sin duplicar la cifra."""
    assert DB_URL is not None
    database = Database(DB_URL)
    tied_capture = datetime(2035, 10, 28, 12, 0, tzinfo=UTC)
    prior_refresh = datetime(2035, 10, 28, 13, 0, tzinfo=UTC)
    winner_refresh = datetime(2035, 10, 28, 14, 0, tzinfo=UTC)
    replacement_capture = datetime(2035, 10, 28, 15, 0, tzinfo=UTC)

    def cleanup() -> None:
        with psycopg.connect(DB_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                "delete from sales_daily_totals "
                "where restaurant_id = 'R001' and sales_date in (%s, %s)",
                (DST_PRIOR_SOURCE_DATE, DST_WINNER_SOURCE_DATE),
            )
            cursor.execute(
                "delete from sales_hourly where restaurant_id = 'R001' and source_date in (%s, %s)",
                (DST_PRIOR_SOURCE_DATE, DST_WINNER_SOURCE_DATE),
            )

    cleanup()
    try:
        # D contiene 22:00 y los dos folds de las 02:00 del D+1.
        prior_day = _day(
            [(22, "5.00"), (2, "10.00"), (2, "20.00")],
            source_date=DST_PRIOR_SOURCE_DATE,
        )
        winner_day = _day(
            [
                (22, "50.00"),
                (2, "100.00"),
                (2, "200.00"),
                (10, "30.00"),
                (23, "40.00"),
                (0, "60.00"),
            ],
            source_date=DST_WINNER_SOURCE_DATE,
        )
        database.upsert_sales_day(
            prior_day,
            captured_at=tied_capture,
            header_date=DST_PRIOR_SOURCE_DATE,
        )
        # D+1 repite ese carryover físico y añade su jornada principal.
        database.upsert_sales_day(
            winner_day,
            captured_at=tied_capture,
            header_date=DST_WINNER_SOURCE_DATE,
        )

        with psycopg.connect(DB_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                "select source_date, fold, net from sales_hourly "
                "where restaurant_id = 'R001' and calendar_date = %s and hour = 2 "
                "order by source_date, fold",
                (DST_WINNER_SOURCE_DATE,),
            )
            assert cursor.fetchall() == [
                (DST_PRIOR_SOURCE_DATE, 0, Decimal("10.00")),
                (DST_PRIOR_SOURCE_DATE, 1, Decimal("20.00")),
                (DST_WINNER_SOURCE_DATE, 0, Decimal("100.00")),
                (DST_WINNER_SOURCE_DATE, 1, Decimal("200.00")),
            ]
            cursor.execute(
                "select net, hourly_net_sum, gc, quality from sales_daily_totals "
                "where restaurant_id = 'R001' and sales_date = %s",
                (DST_PRIOR_SOURCE_DATE,),
            )
            assert cursor.fetchone() == (
                Decimal("350.00"),
                Decimal("350.00"),
                3,
                "rebucketed",
            )
            cursor.execute(
                "select net, hourly_net_sum, gc, quality from sales_daily_totals "
                "where restaurant_id = 'R001' and sales_date = %s",
                (DST_WINNER_SOURCE_DATE,),
            )
            assert cursor.fetchone() == (
                Decimal("130.00"),
                Decimal("130.00"),
                3,
                "rebucketed",
            )

        # Un timestamp posterior manda incluso cuando source_date es anterior.
        database.upsert_sales_day(
            prior_day,
            captured_at=prior_refresh,
            header_date=DST_PRIOR_SOURCE_DATE,
        )
        with psycopg.connect(DB_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                "select net, hourly_net_sum, gc, quality from sales_daily_totals "
                "where restaurant_id = 'R001' and sales_date = %s",
                (DST_PRIOR_SOURCE_DATE,),
            )
            assert cursor.fetchone() == (
                Decimal("35.00"),
                Decimal("35.00"),
                3,
                "clean",
            )

        database.upsert_sales_day(
            winner_day,
            captured_at=winner_refresh,
            header_date=DST_WINNER_SOURCE_DATE,
        )
        with psycopg.connect(DB_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                "select net, hourly_net_sum, gc, quality from sales_daily_totals "
                "where restaurant_id = 'R001' and sales_date = %s",
                (DST_PRIOR_SOURCE_DATE,),
            )
            assert cursor.fetchone() == (
                Decimal("350.00"),
                Decimal("350.00"),
                3,
                "rebucketed",
            )

        # El snapshot ganador se sustituye por otro sin el carryover. La copia
        # anterior vuelve a ser efectiva y el total antiguo no queda huérfano.
        database.upsert_sales_day(
            _day(
                [(10, "31.00"), (23, "41.00"), (0, "61.00")],
                source_date=DST_WINNER_SOURCE_DATE,
            ),
            captured_at=replacement_capture,
            header_date=DST_WINNER_SOURCE_DATE,
        )

        with psycopg.connect(DB_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                "select net, hourly_net_sum, gc, quality from sales_daily_totals "
                "where restaurant_id = 'R001' and sales_date = %s",
                (DST_PRIOR_SOURCE_DATE,),
            )
            assert cursor.fetchone() == (
                Decimal("35.00"),
                Decimal("35.00"),
                3,
                "clean",
            )
            cursor.execute(
                "select net, hourly_net_sum, gc from sales_daily_totals "
                "where restaurant_id = 'R001' and sales_date = %s",
                (DST_WINNER_SOURCE_DATE,),
            )
            assert cursor.fetchone() == (Decimal("133.00"), Decimal("133.00"), 3)
    finally:
        cleanup()
