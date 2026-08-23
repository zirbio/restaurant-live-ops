"""Fixture sintético para cruzar el worker real con PostgREST y useDay."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

import psycopg

from restaurant_live_ops.db import Database
from restaurant_live_ops.sales_source.parser import SalesDay, SalesDayTotals, SalesHour

RESTAURANT_ID = "R001"
PRIOR_SOURCE_DATE = date(2036, 10, 25)
WINNER_SOURCE_DATE = date(2036, 10, 26)
Action = Literal["prepare", "cleanup"]


def _hour(
    hour: int,
    net: str,
    gc: int,
    drive_through_net: str,
    drive_through_cars: int,
    delivery_net: str,
    delivery_count: int,
) -> SalesHour:
    return SalesHour(
        hour=hour,
        net=Decimal(net),
        gross=None,
        gc=gc,
        drive_through_net=Decimal(drive_through_net),
        drive_through_gross=None,
        drive_through_cars=drive_through_cars,
        kvs=None,
        r2p=None,
        oepe=None,
        delivery_net=Decimal(delivery_net),
        delivery_gross=None,
        delivery_count=delivery_count,
    )


def _day(source_date: date, hours: list[SalesHour]) -> SalesDay:
    return SalesDay(
        restaurant_id=RESTAURANT_ID,
        sales_date=source_date,
        hours=hours,
        totals=SalesDayTotals(
            net=sum((hour.net or Decimal(0) for hour in hours), Decimal(0)),
            gross=None,
            gc=sum((hour.gc or 0 for hour in hours), 0),
            drive_through_net=sum(
                (hour.drive_through_net or Decimal(0) for hour in hours), Decimal(0)
            ),
            drive_through_gross=None,
            drive_through_cars=sum((hour.drive_through_cars or 0 for hour in hours), 0),
            kvs=None,
            r2p=None,
            oepe=None,
            delivery_net=sum((hour.delivery_net or Decimal(0) for hour in hours), Decimal(0)),
            delivery_gross=None,
            delivery_count=sum((hour.delivery_count or 0 for hour in hours), 0),
        ),
    )


def _cleanup(db_url: str, user_id: UUID) -> None:
    with psycopg.connect(db_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "delete from public.sales_daily_totals "
            "where restaurant_id = %s and sales_date in (%s, %s)",
            (RESTAURANT_ID, PRIOR_SOURCE_DATE, WINNER_SOURCE_DATE),
        )
        cursor.execute(
            "delete from public.sales_hourly where restaurant_id = %s and source_date in (%s, %s)",
            (RESTAURANT_ID, PRIOR_SOURCE_DATE, WINNER_SOURCE_DATE),
        )
        cursor.execute(
            "delete from public.app_user_access where user_id = %s and restaurant_id = %s",
            (user_id, RESTAURANT_ID),
        )


def _prepare(db_url: str, user_id: UUID) -> None:
    _cleanup(db_url, user_id)
    with psycopg.connect(db_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "insert into public.app_user_access (user_id, restaurant_id) "
            "values (%s, %s) on conflict do nothing",
            (user_id, RESTAURANT_ID),
        )

    prior = _day(
        PRIOR_SOURCE_DATE,
        [
            _hour(22, "5.00", 1, "1.00", 1, "0.00", 0),
            _hour(2, "10.00", 2, "4.00", 1, "2.00", 1),
            _hour(2, "20.00", 3, "6.00", 2, "4.00", 2),
        ],
    )
    winner = _day(
        WINNER_SOURCE_DATE,
        [
            _hour(22, "50.00", 5, "20.00", 2, "10.00", 1),
            _hour(2, "100.00", 10, "40.00", 4, "20.00", 2),
            _hour(2, "200.00", 20, "80.00", 8, "40.00", 4),
            _hour(10, "30.00", 3, "12.00", 1, "6.00", 1),
            _hour(23, "40.00", 4, "16.00", 2, "8.00", 1),
            _hour(0, "60.00", 6, "24.00", 3, "12.00", 2),
        ],
    )

    database = Database(db_url)
    database.upsert_sales_day(
        prior,
        captured_at=datetime(2036, 10, 25, 23, 0, tzinfo=UTC),
        header_date=PRIOR_SOURCE_DATE,
    )
    database.upsert_sales_day(
        winner,
        captured_at=datetime(2036, 10, 26, 12, 0, tzinfo=UTC),
        header_date=WINNER_SOURCE_DATE,
    )


def _arguments() -> tuple[Action, UUID]:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "cleanup"))
    parser.add_argument("--user-id", required=True)
    parsed = parser.parse_args()
    return cast(Action, parsed.action), UUID(str(parsed.user_id))


def main() -> int:
    action, user_id = _arguments()
    db_url = os.environ.get("LOCAL_SUPABASE_DB_URL")
    if not db_url:
        raise RuntimeError("falta LOCAL_SUPABASE_DB_URL")
    if action == "prepare":
        _prepare(db_url, user_id)
    else:
        _cleanup(db_url, user_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
