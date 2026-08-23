from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from restaurant_live_ops.db import (
    _HOURLY_COLUMNS,
    _STAFFING_COLUMNS,
    Database,
    _insert_if_absent_sql,
    _upsert_sql,
    projection_rows,
    sales_daily_rows,
    sales_hourly_rows,
    staffing_rows,
)
from restaurant_live_ops.sales_source.parser import (
    SalesDay,
    SalesSequenceError,
    parse_hourly_response,
)
from restaurant_live_ops.workforce_source.hourly import HourlyStaffing
from restaurant_live_ops.workforce_source.projections import HourlyProjection

CAPTURED = datetime(2026, 7, 26, 16, 20, tzinfo=UTC)


def _day(
    rows: list[dict[str, Any]],
    restaurant_id: str = "R002",
    *,
    source_date: date = date(2026, 7, 26),
) -> SalesDay:
    prepared_rows = [dict(row) for row in rows]
    if not any("_s0" in row for row in prepared_rows):
        prepared_rows.append({"_s0": "Total", "_s1": "0"})
    return parse_hourly_response(
        {"success": True, "metaData": {"fields": ["0", "12"]}, "rows": prepared_rows},
        restaurant_id=restaurant_id,
        sales_date=source_date,
    )


def test_missing_values_stay_none_in_the_row() -> None:
    filas = sales_hourly_rows(_day([{"0": "14", "1": "100,00", "4": "", "9": ""}]), CAPTURED)
    (fila,) = filas
    assert fila["net"] == Decimal("100.00")
    assert fila["drive_through_net"] is None
    assert fila["oepe"] is None


def test_totals_row_is_written_as_its_own_hour() -> None:
    # La fila de totales de la fuente de ventas es también la última hora: debe guardarse.
    filas = sales_hourly_rows(
        _day([{"0": "14", "1": "100,00"}, {"0": "15", "1": "50,00", "_s0": "Total", "_s1": "150"}]),
        CAPTURED,
    )
    assert [f["hour"] for f in filas] == [14, 15]
    assert filas[1]["net"] == Decimal("50.00")


def test_rows_without_an_hour_are_skipped() -> None:
    filas = sales_hourly_rows(
        _day([{"0": "14", "1": "100,00"}, {"_s0": "Total", "_s1": "100,00"}]), CAPTURED
    )
    assert [f["hour"] for f in filas] == [14]


def test_row_carries_keys_and_capture_time() -> None:
    (fila,) = sales_hourly_rows(_day([{"0": "3", "1": "10,00"}]), CAPTURED)
    assert fila["restaurant_id"] == "R002"
    assert fila["source_date"] == date(2026, 7, 26)
    assert fila["sales_date"] == date(2026, 7, 25)
    assert fila["calendar_date"] == date(2026, 7, 26)
    assert fila["hour"] == 3  # la madrugada de R003 también se guarda
    assert fila["fold"] == 0
    assert fila["captured_at"] == CAPTURED


def test_rows_preserve_both_occurrences_of_the_repeated_dst_hour() -> None:
    day = _day(
        [
            {"0": "1", "1": "10,00"},
            {"0": "2", "1": "20,00"},
            {"0": "2", "1": "30,00"},
            {"0": "3", "1": "40,00", "_s0": "Total", "_s1": "100,00"},
        ],
        restaurant_id="R003",
        source_date=date(2026, 10, 25),
    )

    filas = sales_hourly_rows(day, CAPTURED)

    assert [(row["calendar_date"], row["hour"], row["fold"]) for row in filas] == [
        (date(2026, 10, 25), 1, 0),
        (date(2026, 10, 25), 2, 0),
        (date(2026, 10, 25), 2, 1),
        (date(2026, 10, 25), 3, 0),
    ]
    assert {row["source_date"] for row in filas} == {date(2026, 10, 25)}
    assert {row["sales_date"] for row in filas} == {date(2026, 10, 24)}


def test_every_hourly_column_is_present_in_the_row() -> None:
    (fila,) = sales_hourly_rows(_day([{"0": "14", "1": "100,00"}]), CAPTURED)
    assert set(fila) == {
        "restaurant_id",
        "source_date",
        "sales_date",
        "calendar_date",
        "hour",
        "fold",
        "net",
        "gross",
        "gc",
        "drive_through_net",
        "drive_through_gross",
        "drive_through_cars",
        "delivery_net",
        "delivery_gross",
        "delivery_count",
        "kvs",
        "r2p",
        "oepe",
        "captured_at",
        "source",
    }


def test_database_refuses_an_ambiguous_sequence_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day = _day(
        [
            {"0": 22},
            {"0": 0},
            {"0": 10},
            {"0": 0},
            {"0": 10},
            {"0": 0, "_s0": "Total", "_s1": "0"},
        ],
        restaurant_id="R003",
    )
    database = Database("postgresql://unused")

    def unexpected_connect() -> None:
        raise AssertionError("la secuencia debe validarse antes de abrir la conexión")

    monkeypatch.setattr(database, "_connect", unexpected_connect)

    with pytest.raises(SalesSequenceError, match="más de dos medianoches"):
        database.upsert_sales_day(
            day,
            captured_at=CAPTURED,
            header_date=day.sales_date,
        )


def test_projection_rows_carry_hour_and_values() -> None:
    filas = projection_rows(
        "R001",
        date(2026, 7, 26),
        [HourlyProjection(hour=14, sales=Decimal("100.5"), guest_counts=Decimal("12"))],
        fetched_at=CAPTURED,
        expected_hours=(14,),
    )
    assert filas == [
        {
            "restaurant_id": "R001",
            "sales_date": date(2026, 7, 26),
            "hour": 14,
            "sales": Decimal("100.5"),
            "guest_counts": Decimal("12"),
            "expected_hours": [14],
            "fetched_at": CAPTURED,
        }
    ]


def test_no_projections_yields_no_rows() -> None:
    assert (
        projection_rows(
            "R001",
            date(2026, 7, 26),
            [],
            fetched_at=CAPTURED,
            expected_hours=(14,),
        )
        == []
    )


def test_staffing_row_carries_every_declared_column() -> None:
    # Una columna que se declara y no se rellena —o al revés— rompe el insert
    # entero: aquí se fija que la fila y la lista de columnas son la misma.
    (fila,) = staffing_rows(
        "R001",
        date(2026, 7, 26),
        [
            HourlyStaffing(
                hour=14,
                clocked_count=9,
                assigned_count=10,
                clocked_minutes=540,
                assigned_minutes=600,
                open_anomalies=2,
                crew_clocked_count=7,
                crew_assigned_count=8,
                crew_clocked_minutes=420,
                crew_assigned_minutes=480,
                crew_open_anomalies=1,
            )
        ],
        fetched_at=CAPTURED,
        expected_hours=(14,),
    )
    assert set(fila) == set(_STAFFING_COLUMNS)
    # El aviso viaja con el recuento de equipo, que es el que se pinta, y el
    # total sigue siendo el diagnóstico completo.
    assert fila["crew_open_anomalies"] == 1
    assert fila["open_anomalies"] == 2


def test_daily_row_keeps_exact_source_totals_only_for_one_operating_day() -> None:
    day = _day([{"0": "14", "1": "100,00", "_s0": "Total", "_s1": "100,00"}])
    (fila,) = sales_daily_rows(
        day,
        captured_at=CAPTURED,
        header_date=date(2026, 7, 26),
        source="live",
    )
    assert fila["source"] == "live"
    assert fila["header_date"] == date(2026, 7, 26)
    assert fila["quality"] == "clean"
    assert fila["hourly_net_sum"] == Decimal("100.00")


def test_daily_rows_split_additive_values_without_guessing_service_totals() -> None:
    day = _day(
        [
            {"0": 22, "1": "10", "3": 1, "4": "3", "10": "2"},
            {"0": 0, "1": "20", "3": 2, "4": "6", "10": "4"},
            {"0": 10, "1": "30", "3": 3, "4": "9", "10": "6"},
            {"0": 23, "1": "40", "3": 4, "4": "12", "10": "8"},
            {
                "0": 0,
                "1": "50",
                "3": 5,
                "4": "15",
                "10": "10",
                "_s0": "Total",
                "_s1": "150",
                "_s3": 15,
                "_s7": 80,
                "_s8": 110,
                "_s9": 150,
            },
        ],
        restaurant_id="R003",
        source_date=date(2026, 8, 1),
    )

    rows = sales_daily_rows(
        day,
        captured_at=CAPTURED,
        header_date=date(2026, 8, 1),
        source="live",
    )

    assert [row["sales_date"] for row in rows] == [date(2026, 7, 31), date(2026, 8, 1)]
    assert [(row["net"], row["gc"]) for row in rows] == [
        (Decimal("30"), 3),
        (Decimal("120"), 12),
    ]
    assert [row["drive_through_net"] for row in rows] == [Decimal("9"), Decimal("36")]
    assert [row["delivery_net"] for row in rows] == [Decimal("6"), Decimal("24")]
    for row in rows:
        assert row["quality"] == "rebucketed"
        assert row["kvs"] is None
        assert row["r2p"] is None
        assert row["oepe"] is None
        assert row["header_date"] is None
        assert row["totals_mismatch"] is None


def test_insert_sql_no_pisa_lo_que_ya_hay() -> None:
    sql = _insert_if_absent_sql(
        "sales_hourly", _HOURLY_COLUMNS, ("restaurant_id", "sales_date", "hour")
    )
    assert "on conflict (restaurant_id, sales_date, hour) do nothing" in sql
    assert "do update" not in sql


def test_upsert_sql_sigue_actualizando_para_el_dia_en_curso() -> None:
    # El ciclo del día en curso SÍ debe sobrescribir: cada 12 minutos trae
    # horas más completas del mismo día.
    sql = _upsert_sql("sales_hourly", _HOURLY_COLUMNS, ("restaurant_id", "sales_date", "hour"))
    assert "do update set" in sql
