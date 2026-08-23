from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from restaurant_live_ops.db import Database
from restaurant_live_ops.sales_source.parser import SalesDay, SalesDayTotals, SalesHour
from restaurant_live_ops.workforce_source.hourly import HourlyStaffing
from restaurant_live_ops.workforce_source.projections import HourlyProjection

CAPTURED = datetime(2026, 1, 2, 11, 0, tzinfo=UTC)


class RecordingCursor:
    def __init__(
        self,
        *,
        fetchone_results: list[dict[str, object]] | None = None,
        fetchall_results: list[list[dict[str, object]]] | None = None,
    ) -> None:
        self.statements: list[str] = []
        self.parameters: list[object] = []
        self.fetchone_results = list(fetchone_results or [])
        self.fetchall_results = list(fetchall_results or [])

    def __enter__(self) -> RecordingCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: object, _params: object = None) -> None:
        self.statements.append(str(query))
        self.parameters.append(_params)

    def executemany(self, query: object, _params: object) -> None:
        self.statements.append(str(query))
        self.parameters.append(_params)

    def fetchone(self) -> dict[str, object]:
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return {"id": 1, "dia": None}

    def fetchall(self) -> list[dict[str, object]]:
        if self.fetchall_results:
            return self.fetchall_results.pop(0)
        return []


class RecordingConnection:
    def __init__(self, cursor: RecordingCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> RecordingConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> RecordingCursor:
        return self._cursor


def recording_database(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Database, RecordingCursor]:
    cursor = RecordingCursor()
    connection = RecordingConnection(cursor)
    database = Database("postgresql://unused")
    monkeypatch.setattr(database, "_connect", lambda: connection)
    return database, cursor


def sales_day() -> SalesDay:
    return SalesDay(
        restaurant_id="R001",
        sales_date=date(2026, 1, 2),
        hours=[
            SalesHour(
                hour=10,
                net=Decimal("10.00"),
                gross=Decimal("11.00"),
                gc=2,
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
            net=Decimal("10.00"),
            gross=Decimal("11.00"),
            gc=2,
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


def test_ingest_run_is_opened_for_one_restaurant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, cursor = recording_database(monkeypatch)

    database.start_run("sales", "R001", started_at=CAPTURED)

    assert cursor.statements == [
        "insert into ingest_runs (restaurant_id, source, started_at, status) "
        "values (%s, %s, %s, 'running') returning id"
    ]


def test_sales_write_uses_only_the_neutral_sales_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, cursor = recording_database(monkeypatch)

    database.upsert_sales_day(
        sales_day(),
        captured_at=CAPTURED,
        header_date=date(2026, 1, 2),
    )

    sql = "\n".join(cursor.statements)
    assert "insert into sales_hourly" in sql
    assert "insert into sales_daily_totals" in sql
    assert "legacy_sales_" not in sql
    assert "legacy_captures" not in sql


def test_live_snapshot_replaces_one_source_and_recomputes_every_affected_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = RecordingCursor(
        fetchall_results=[[{"sales_date": date(2026, 1, 1)}]],
    )
    database = Database("postgresql://unused")
    monkeypatch.setattr(database, "_connect", lambda: RecordingConnection(cursor))

    database.upsert_sales_day(
        sales_day(),
        captured_at=CAPTURED,
        header_date=date(2026, 1, 2),
    )

    sql = "\n".join(cursor.statements)
    assert "pg_advisory_xact_lock" in sql
    assert "select distinct sales_date from sales_hourly" in sql
    assert "delete from sales_hourly" in sql
    assert "source_date" in sql
    assert "insert into sales_hourly" in sql
    assert "insert into sales_daily_totals" in sql
    assert "delete from sales_daily_totals" in sql


def test_empty_sales_snapshot_returns_before_opening_a_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = SalesDay(
        restaurant_id="R001",
        sales_date=date(2026, 1, 2),
        hours=[],
        totals=sales_day().totals,
    )
    database = Database("postgresql://unused")

    def unexpected_connect() -> None:
        raise AssertionError("una captura vacía no puede tocar el snapshot existente")

    monkeypatch.setattr(database, "_connect", unexpected_connect)

    assert (
        database.upsert_sales_day(
            empty,
            captured_at=CAPTURED,
            header_date=date(2026, 1, 2),
        )
        == 0
    )


def test_explicit_recapture_preserves_an_existing_live_operating_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = RecordingCursor(fetchone_results=[{"exists": True}])
    database = Database("postgresql://unused")
    monkeypatch.setattr(database, "_connect", lambda: RecordingConnection(cursor))

    assert (
        database.insert_sales_day_if_absent(
            sales_day(),
            captured_at=CAPTURED,
            source="backfill",
        )
        == 0
    )

    mutation_sql = [
        statement
        for statement in cursor.statements
        if statement.lstrip().startswith(("insert into", "update", "delete"))
    ]
    assert mutation_sql == []
    assert "source_date = %s" in "\n".join(cursor.statements)


def test_sales_reads_use_the_neutral_hourly_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, cursor = recording_database(monkeypatch)

    database.restaurants_with_hours(date(2026, 1, 2))
    database.existing_sales_days(date(2026, 1, 1), date(2026, 1, 2))
    database.earliest_sales_day()

    sql = "\n".join(cursor.statements)
    assert "sales_hourly" in sql
    assert "legacy_hourly" not in sql


def test_workforce_writes_use_only_the_neutral_workforce_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, cursor = recording_database(monkeypatch)

    database.upsert_projections(
        "R001",
        date(2026, 1, 2),
        [HourlyProjection(hour=10, sales=Decimal("10.00"), guest_counts=Decimal("2"))],
        fetched_at=CAPTURED,
        expected_hours=(10,),
    )
    database.upsert_staffing(
        "R001",
        date(2026, 1, 2),
        [
            HourlyStaffing(
                hour=10,
                clocked_count=2,
                assigned_count=3,
                clocked_minutes=120,
                assigned_minutes=180,
                open_anomalies=0,
            )
        ],
        fetched_at=CAPTURED,
        expected_hours=(10,),
    )

    sql = "\n".join(cursor.statements)
    assert "workforce_projection_hourly" in sql
    assert "workforce_staffing_hourly" in sql
    assert "legacy_workforce_" not in sql


def test_partial_workforce_snapshots_never_delete_omitted_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, cursor = recording_database(monkeypatch)

    database.upsert_projections(
        "R001",
        date(2026, 1, 2),
        [HourlyProjection(hour=10, sales=Decimal("10.00"), guest_counts=Decimal("2"))],
        fetched_at=CAPTURED,
        expected_hours=(10,),
    )
    database.upsert_staffing(
        "R001",
        date(2026, 1, 2),
        [
            HourlyStaffing(
                hour=10,
                clocked_count=2,
                assigned_count=3,
                clocked_minutes=120,
                assigned_minutes=180,
                open_anomalies=0,
            )
        ],
        fetched_at=CAPTURED,
        expected_hours=(10,),
    )

    mutations = "\n".join(
        statement
        for statement in cursor.statements
        if statement.lstrip().startswith(("insert into", "update", "delete"))
    )
    assert "delete from workforce_" not in mutations
    assert mutations.count("fetched_at = excluded.fetched_at") == 2


@pytest.mark.parametrize("table", ["projection", "staffing"])
@pytest.mark.parametrize("received_hours", [[], [8]])
def test_initial_workforce_snapshot_requires_the_exact_expected_hours_before_writing(
    monkeypatch: pytest.MonkeyPatch,
    table: str,
    received_hours: list[int],
) -> None:
    database, cursor = recording_database(monkeypatch)

    with pytest.raises(RuntimeError, match="snapshot de personal incompleto"):
        if table == "projection":
            database.upsert_projections(
                "R001",
                date(2026, 1, 2),
                [
                    HourlyProjection(
                        hour=hour,
                        sales=Decimal("10"),
                        guest_counts=Decimal("1"),
                    )
                    for hour in received_hours
                ],
                fetched_at=CAPTURED,
                expected_hours=(8, 9),
            )
        else:
            database.upsert_staffing(
                "R001",
                date(2026, 1, 2),
                [
                    HourlyStaffing(
                        hour=hour,
                        clocked_count=1,
                        assigned_count=1,
                        clocked_minutes=60,
                        assigned_minutes=60,
                        open_anomalies=0,
                    )
                    for hour in received_hours
                ],
                fetched_at=CAPTURED,
                expected_hours=(8, 9),
            )

    mutations = [
        statement
        for statement in cursor.statements
        if statement.lstrip().startswith(("insert into", "update", "delete"))
    ]
    assert mutations == []


@pytest.mark.parametrize("table", ["projection", "staffing"])
def test_existing_workforce_snapshot_rejects_an_omitted_hour_before_writing(
    monkeypatch: pytest.MonkeyPatch,
    table: str,
) -> None:
    cursor = RecordingCursor(fetchall_results=[[{"hour": 8}, {"hour": 9}]])
    database = Database("postgresql://unused")
    monkeypatch.setattr(database, "_connect", lambda: RecordingConnection(cursor))

    with pytest.raises(RuntimeError, match="snapshot de personal incompleto"):
        if table == "projection":
            database.upsert_projections(
                "R001",
                date(2026, 1, 2),
                [HourlyProjection(hour=8, sales=Decimal("10"), guest_counts=Decimal("1"))],
                fetched_at=CAPTURED,
                expected_hours=(8, 9),
            )
        else:
            database.upsert_staffing(
                "R001",
                date(2026, 1, 2),
                [
                    HourlyStaffing(
                        hour=8,
                        clocked_count=1,
                        assigned_count=1,
                        clocked_minutes=60,
                        assigned_minutes=60,
                        open_anomalies=0,
                    )
                ],
                fetched_at=CAPTURED,
                expected_hours=(8, 9),
            )

    mutations = [
        statement
        for statement in cursor.statements
        if statement.lstrip().startswith(("insert into", "update", "delete"))
    ]
    assert mutations == []


def test_complete_workforce_refresh_keeps_every_existing_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = RecordingCursor(
        fetchall_results=[
            [
                {"hour": 8, "expected_hours": [8, 9]},
                {"hour": 9, "expected_hours": [8, 9]},
            ]
        ]
    )
    database = Database("postgresql://unused")
    monkeypatch.setattr(database, "_connect", lambda: RecordingConnection(cursor))

    written = database.upsert_projections(
        "R001",
        date(2026, 1, 2),
        [
            HourlyProjection(hour=8, sales=Decimal("10"), guest_counts=Decimal("1")),
            HourlyProjection(hour=9, sales=Decimal("20"), guest_counts=Decimal("2")),
        ],
        fetched_at=CAPTURED,
        expected_hours=(8, 9),
    )

    assert written == 2
    assert "insert into workforce_projection_hourly" in "\n".join(cursor.statements)


def test_incomplete_day_query_uses_only_neutral_sales_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, cursor = recording_database(monkeypatch)

    database.incomplete_sales_days(
        date(2026, 1, 1),
        date(2026, 1, 2),
        ("R001", "R002"),
    )

    sql = "\n".join(cursor.statements)
    assert "sales_daily_totals" in sql
    assert "sales_hourly" in sql
    assert "legacy_sales_" not in sql
