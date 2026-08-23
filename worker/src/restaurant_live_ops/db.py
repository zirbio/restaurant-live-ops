"""Escrituras en Supabase.

Se guardan los datos crudos y se calcula al leer: nada de agregados que luego
no se puedan auditar. Cada ciclo abre y cierra una fila en ``ingest_runs``,
que es lo que la interfaz usa para decir "actualizado hace X minutos".
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from restaurant_live_ops.public_errors import WORKFORCE_SNAPSHOT_ERROR
from restaurant_live_ops.sales_source.parser import SalesDay
from restaurant_live_ops.workforce_source.hourly import HourlyStaffing
from restaurant_live_ops.workforce_source.projections import HourlyProjection

_HOURLY_COLUMNS = (
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
)

_DAILY_COLUMNS = (
    "restaurant_id",
    "sales_date",
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
    "hourly_net_sum",
    "totals_mismatch",
    "header_date",
    "captured_at",
    "source",
    "quality",
)

_PROJECTION_COLUMNS = (
    "restaurant_id",
    "sales_date",
    "hour",
    "sales",
    "guest_counts",
    "expected_hours",
    "fetched_at",
)

_STAFFING_COLUMNS = (
    "restaurant_id",
    "sales_date",
    "hour",
    "clocked_count",
    "assigned_count",
    "clocked_minutes",
    "assigned_minutes",
    "open_anomalies",
    "crew_clocked_count",
    "crew_assigned_count",
    "crew_clocked_minutes",
    "crew_assigned_minutes",
    "crew_open_anomalies",
    "expected_hours",
    "fetched_at",
)


class IncompleteWorkforceSnapshotError(RuntimeError):
    """La captura omite alguna hora que ya formaba parte del snapshot."""


_HOURLY_KEYS = (
    "restaurant_id",
    "source_date",
    "calendar_date",
    "hour",
    "fold",
)

_RECOMPUTE_DAILY_SQL = """
with ranked_occurrences as (
    select
        hourly.*,
        row_number() over (
            partition by restaurant_id, calendar_date, hour, fold
            order by captured_at desc, source_date desc
        ) as occurrence_priority
    from sales_hourly hourly
    where restaurant_id = %(restaurant_id)s
), effective_occurrences as (
    select *
    from ranked_occurrences
    where occurrence_priority = 1
), source_profile as (
    select source_date, count(distinct sales_date) as mapped_days
    from sales_hourly
    where restaurant_id = %(restaurant_id)s
    group by source_date
), aggregate as (
    select
        h.restaurant_id,
        h.sales_date,
        sum(h.net) as net,
        sum(h.gross) as gross,
        sum(h.gc)::integer as gc,
        sum(h.drive_through_net) as drive_through_net,
        sum(h.drive_through_gross) as drive_through_gross,
        sum(h.drive_through_cars)::integer as drive_through_cars,
        sum(h.delivery_net) as delivery_net,
        sum(h.delivery_gross) as delivery_gross,
        sum(h.delivery_count)::integer as delivery_count,
        coalesce(sum(h.net), 0) as hourly_net_sum,
        max(h.captured_at) as captured_at,
        (array_agg(h.source order by h.captured_at desc, h.source_date desc))[1] as source,
        case
            when count(distinct h.source_date) = 1 and max(profile.mapped_days) = 1
            then min(h.source_date)
        end as exact_source_date,
        case
            when count(distinct h.source_date) = 1 and max(profile.mapped_days) = 1
            then 'clean'
            else 'rebucketed'
        end as quality
    from effective_occurrences h
    join source_profile profile on profile.source_date = h.source_date
    where h.restaurant_id = %(restaurant_id)s
      and h.sales_date = %(sales_date)s
    group by h.restaurant_id, h.sales_date
), prepared as (
    select
        aggregate.restaurant_id,
        aggregate.sales_date,
        aggregate.net,
        aggregate.gross,
        aggregate.gc,
        aggregate.drive_through_net,
        aggregate.drive_through_gross,
        aggregate.drive_through_cars,
        aggregate.delivery_net,
        aggregate.delivery_gross,
        aggregate.delivery_count,
        case
            when aggregate.exact_source_date = %(candidate_source_date)s
             and aggregate.sales_date = %(candidate_sales_date)s then %(kvs)s
            when current.header_date = aggregate.exact_source_date then current.kvs
        end as kvs,
        case
            when aggregate.exact_source_date = %(candidate_source_date)s
             and aggregate.sales_date = %(candidate_sales_date)s then %(r2p)s
            when current.header_date = aggregate.exact_source_date then current.r2p
        end as r2p,
        case
            when aggregate.exact_source_date = %(candidate_source_date)s
             and aggregate.sales_date = %(candidate_sales_date)s then %(oepe)s
            when current.header_date = aggregate.exact_source_date then current.oepe
        end as oepe,
        aggregate.hourly_net_sum,
        case
            when aggregate.exact_source_date = %(candidate_source_date)s
             and aggregate.sales_date = %(candidate_sales_date)s then %(totals_mismatch)s
            when current.header_date = aggregate.exact_source_date then current.totals_mismatch
        end as totals_mismatch,
        case
            when aggregate.exact_source_date = %(candidate_source_date)s
             and aggregate.sales_date = %(candidate_sales_date)s then %(header_date)s
            when current.header_date = aggregate.exact_source_date then current.header_date
        end as header_date,
        aggregate.captured_at,
        aggregate.source,
        aggregate.quality
    from aggregate
    left join sales_daily_totals current
      on current.restaurant_id = aggregate.restaurant_id
     and current.sales_date = aggregate.sales_date
)
insert into sales_daily_totals (
    restaurant_id, sales_date, net, gross, gc,
    drive_through_net, drive_through_gross, drive_through_cars,
    delivery_net, delivery_gross, delivery_count,
    kvs, r2p, oepe, hourly_net_sum, totals_mismatch, header_date,
    captured_at, source, quality
)
select
    restaurant_id, sales_date, net, gross, gc,
    drive_through_net, drive_through_gross, drive_through_cars,
    delivery_net, delivery_gross, delivery_count,
    kvs, r2p, oepe, hourly_net_sum, totals_mismatch, header_date,
    captured_at, source, quality
from prepared
on conflict (restaurant_id, sales_date) do update set
    net = excluded.net,
    gross = excluded.gross,
    gc = excluded.gc,
    drive_through_net = excluded.drive_through_net,
    drive_through_gross = excluded.drive_through_gross,
    drive_through_cars = excluded.drive_through_cars,
    delivery_net = excluded.delivery_net,
    delivery_gross = excluded.delivery_gross,
    delivery_count = excluded.delivery_count,
    kvs = excluded.kvs,
    r2p = excluded.r2p,
    oepe = excluded.oepe,
    hourly_net_sum = excluded.hourly_net_sum,
    totals_mismatch = excluded.totals_mismatch,
    header_date = excluded.header_date,
    captured_at = excluded.captured_at,
    source = excluded.source,
    quality = excluded.quality
"""


def sales_hourly_rows(
    day: SalesDay, captured_at: datetime, *, source: str = "live"
) -> list[dict[str, Any]]:
    """Conserva origen, fecha civil, jornada 06→06 y ocurrencia DST."""
    return [
        {
            "restaurant_id": day.restaurant_id,
            "source_date": day.sales_date,
            "sales_date": occurrence.sales_date,
            "calendar_date": occurrence.calendar_date,
            "hour": occurrence.row.hour,
            "fold": occurrence.fold,
            "net": occurrence.row.net,
            "gross": occurrence.row.gross,
            "gc": occurrence.row.gc,
            "drive_through_net": occurrence.row.drive_through_net,
            "drive_through_gross": occurrence.row.drive_through_gross,
            "drive_through_cars": occurrence.row.drive_through_cars,
            "delivery_net": occurrence.row.delivery_net,
            "delivery_gross": occurrence.row.delivery_gross,
            "delivery_count": occurrence.row.delivery_count,
            "kvs": occurrence.row.kvs,
            "r2p": occurrence.row.r2p,
            "oepe": occurrence.row.oepe,
            "captured_at": captured_at,
            "source": source,
        }
        for occurrence in day.sequenced_hours()
    ]


def projection_rows(
    restaurant_id: str,
    sales_date: date,
    projections: list[HourlyProjection],
    *,
    fetched_at: datetime,
    expected_hours: tuple[int, ...],
) -> list[dict[str, Any]]:
    """Convierte la previsión horaria en filas del contrato neutral."""
    return [
        {
            "restaurant_id": restaurant_id,
            "sales_date": sales_date,
            "hour": p.hour,
            "sales": p.sales,
            "guest_counts": p.guest_counts,
            "expected_hours": list(expected_hours),
            "fetched_at": fetched_at,
        }
        for p in projections
    ]


def staffing_rows(
    restaurant_id: str,
    sales_date: date,
    staffing: list[HourlyStaffing],
    *,
    fetched_at: datetime,
    expected_hours: tuple[int, ...],
) -> list[dict[str, Any]]:
    """Convierte los recuentos horarios en filas del contrato neutral.

    Solo cifras: el identificador de empleado se ha quedado en el worker, y la
    categoría con la que se decidió quién es dotación de turno, también.
    """
    return [
        {
            "restaurant_id": restaurant_id,
            "sales_date": sales_date,
            "hour": s.hour,
            "clocked_count": s.clocked_count,
            "assigned_count": s.assigned_count,
            "clocked_minutes": s.clocked_minutes,
            "assigned_minutes": s.assigned_minutes,
            "open_anomalies": s.open_anomalies,
            "crew_clocked_count": s.crew_clocked_count,
            "crew_assigned_count": s.crew_assigned_count,
            "crew_clocked_minutes": s.crew_clocked_minutes,
            "crew_assigned_minutes": s.crew_assigned_minutes,
            "crew_open_anomalies": s.crew_open_anomalies,
            "expected_hours": list(expected_hours),
            "fetched_at": fetched_at,
        }
        for s in staffing
    ]


def _sum_decimals(values: list[Decimal | None]) -> Decimal | None:
    present = [value for value in values if value is not None]
    return sum(present, Decimal(0)) if present else None


def _sum_integers(values: list[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def sales_daily_rows(
    day: SalesDay,
    *,
    captured_at: datetime,
    header_date: date | None,
    source: str,
) -> list[dict[str, Any]]:
    """Reconstruye aditivos por jornada y conserva metadatos solo si son exactos."""
    by_sales_date: dict[date, list[Any]] = {}
    for occurrence in day.sequenced_hours():
        by_sales_date.setdefault(occurrence.sales_date, []).append(occurrence.row)

    exact_date = next(iter(by_sales_date)) if len(by_sales_date) == 1 else None
    rows: list[dict[str, Any]] = []
    for sales_date, hours in sorted(by_sales_date.items()):
        exact = sales_date == exact_date
        net = _sum_decimals([hour.net for hour in hours])
        rows.append(
            {
                "restaurant_id": day.restaurant_id,
                "sales_date": sales_date,
                "net": net,
                "gross": _sum_decimals([hour.gross for hour in hours]),
                "gc": _sum_integers([hour.gc for hour in hours]),
                "drive_through_net": _sum_decimals([hour.drive_through_net for hour in hours]),
                "drive_through_gross": _sum_decimals([hour.drive_through_gross for hour in hours]),
                "drive_through_cars": _sum_integers([hour.drive_through_cars for hour in hours]),
                "delivery_net": _sum_decimals([hour.delivery_net for hour in hours]),
                "delivery_gross": _sum_decimals([hour.delivery_gross for hour in hours]),
                "delivery_count": _sum_integers([hour.delivery_count for hour in hours]),
                "kvs": day.totals.kvs if exact else None,
                "r2p": day.totals.r2p if exact else None,
                "oepe": day.totals.oepe if exact else None,
                "hourly_net_sum": net or Decimal(0),
                "totals_mismatch": day.totals_mismatch if exact else None,
                "header_date": header_date if exact else None,
                "captured_at": captured_at,
                "source": source,
                "quality": "clean" if exact else "rebucketed",
            }
        )
    return rows


def _upsert_sql(table: str, columns: tuple[str, ...], keys: tuple[str, ...]) -> str:
    cols = ", ".join(columns)
    placeholders = ", ".join(f"%({c})s" for c in columns)
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in keys)
    return (
        f"insert into {table} ({cols}) values ({placeholders}) "
        f"on conflict ({', '.join(keys)}) do update set {updates}"
    )


def _insert_if_absent_sql(table: str, columns: tuple[str, ...], keys: tuple[str, ...]) -> str:
    """Inserta sin pisar: lo que ya está en la base manda sobre lo importado."""
    cols = ", ".join(columns)
    placeholders = ", ".join(f"%({c})s" for c in columns)
    return (
        f"insert into {table} ({cols}) values ({placeholders}) "
        f"on conflict ({', '.join(keys)}) do nothing"
    )


class Database:
    def __init__(self, url: str) -> None:
        self._url = url

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._url, row_factory=dict_row)

    @staticmethod
    def _validate_workforce_hours(
        rows: list[HourlyProjection] | list[HourlyStaffing],
        expected_hours: tuple[int, ...],
    ) -> tuple[int, ...]:
        if (
            not expected_hours
            or len(set(expected_hours)) != len(expected_hours)
            or any(type(hour) is not int or hour < 0 or hour > 23 for hour in expected_hours)
        ):
            raise IncompleteWorkforceSnapshotError(WORKFORCE_SNAPSHOT_ERROR)
        incoming = [row.hour for row in rows]
        if len(incoming) != len(expected_hours) or set(incoming) != set(expected_hours):
            raise IncompleteWorkforceSnapshotError(WORKFORCE_SNAPSHOT_ERROR)
        return tuple(sorted(expected_hours))

    @staticmethod
    def _upsert_complete_workforce_snapshot(
        cur: psycopg.Cursor[dict[str, Any]],
        *,
        table: str,
        columns: tuple[str, ...],
        restaurant_id: str,
        sales_date: date,
        rows: list[dict[str, Any]],
        expected_hours: tuple[int, ...],
    ) -> None:
        cur.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"{table}|{restaurant_id}|{sales_date.isoformat()}",),
        )
        cur.execute(
            f"select hour, expected_hours from {table} "
            "where restaurant_id = %s and sales_date = %s for update",
            (restaurant_id, sales_date),
        )
        existing_rows = cur.fetchall()
        existing_hours = {int(row["hour"]) for row in existing_rows}
        existing_expectations = {
            tuple(int(hour) for hour in row["expected_hours"]) for row in existing_rows
        }
        incoming_hours = {int(row["hour"]) for row in rows}
        if existing_hours - incoming_hours or any(
            expectation != expected_hours for expectation in existing_expectations
        ):
            raise IncompleteWorkforceSnapshotError(WORKFORCE_SNAPSHOT_ERROR)
        if rows:
            cur.executemany(
                _upsert_sql(table, columns, ("restaurant_id", "sales_date", "hour")),
                rows,
            )

    def start_run(self, source: str, restaurant_id: str, *, started_at: datetime) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "insert into ingest_runs (restaurant_id, source, started_at, status) "
                "values (%s, %s, %s, 'running') returning id",
                (restaurant_id, source, started_at),
            )
            row = cur.fetchone()
            if row is None:  # pragma: no cover - un insert…returning siempre devuelve fila
                raise RuntimeError("no se pudo abrir el registro del ciclo en ingest_runs")
            return int(row["id"])

    def finish_run(
        self,
        run_id: int,
        *,
        finished_at: datetime,
        status: str,
        rows_written: int = 0,
        error: str | None = None,
    ) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "update ingest_runs set finished_at = %s, status = %s, "
                "rows_written = %s, error = %s where id = %s",
                (finished_at, status, rows_written, error, run_id),
            )

    @staticmethod
    def _lock_sales(cur: psycopg.Cursor[dict[str, Any]], restaurant_id: str) -> None:
        """Serializa snapshots del mismo local mientras dura la transacción."""
        cur.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"sales|{restaurant_id}",),
        )

    @staticmethod
    def _recompute_sales_days(
        cur: psycopg.Cursor[dict[str, Any]],
        day: SalesDay,
        daily_rows: list[dict[str, Any]],
        affected_dates: set[date],
    ) -> None:
        candidates = {row["sales_date"]: row for row in daily_rows}
        for sales_date in sorted(affected_dates):
            cur.execute(
                "delete from sales_daily_totals totals "
                "where totals.restaurant_id = %s and totals.sales_date = %s "
                "and not exists ("
                "select 1 from sales_hourly hourly "
                "where hourly.restaurant_id = totals.restaurant_id "
                "and hourly.sales_date = totals.sales_date)",
                (day.restaurant_id, sales_date),
            )
            candidate = candidates.get(sales_date)
            cur.execute(
                _RECOMPUTE_DAILY_SQL,
                {
                    "restaurant_id": day.restaurant_id,
                    "sales_date": sales_date,
                    "candidate_source_date": day.sales_date if candidate else None,
                    "candidate_sales_date": sales_date if candidate else None,
                    "kvs": candidate["kvs"] if candidate else None,
                    "r2p": candidate["r2p"] if candidate else None,
                    "oepe": candidate["oepe"] if candidate else None,
                    "totals_mismatch": candidate["totals_mismatch"] if candidate else None,
                    "header_date": candidate["header_date"] if candidate else None,
                },
            )

    def upsert_sales_day(
        self,
        day: SalesDay,
        *,
        captured_at: datetime,
        header_date: date | None,
        source: str = "live",
    ) -> int:
        filas = sales_hourly_rows(day, captured_at, source=source)
        if not filas:
            # Sustituir por vacío borraría el último snapshot válido. La
            # cobertura del pipeline lo marca como error; la DB también falla
            # cerrada si otra ruta intenta saltarse esa barrera.
            return 0
        daily_rows = sales_daily_rows(
            day,
            captured_at=captured_at,
            header_date=header_date,
            source=source,
        )
        with self._connect() as conn, conn.cursor() as cur:
            self._lock_sales(cur, day.restaurant_id)
            cur.execute(
                "select distinct sales_date from sales_hourly "
                "where restaurant_id = %s and source_date = %s",
                (day.restaurant_id, day.sales_date),
            )
            affected_dates = {
                row["sales_date"] for row in cur.fetchall() if isinstance(row["sales_date"], date)
            }
            affected_dates.update(row["sales_date"] for row in daily_rows)
            cur.execute(
                "delete from sales_hourly where restaurant_id = %s and source_date = %s",
                (day.restaurant_id, day.sales_date),
            )
            cur.executemany(
                _upsert_sql("sales_hourly", _HOURLY_COLUMNS, _HOURLY_KEYS),
                filas,
            )
            self._recompute_sales_days(cur, day, daily_rows, affected_dates)
        return len(filas)

    def insert_sales_day_if_absent(
        self, day: SalesDay, *, captured_at: datetime, source: str
    ) -> int:
        """Escribe un día solo si no estaba ya. Devuelve las horas escritas.

        El dato capturado en vivo, con su guard de fecha verificado, manda
        sobre cualquier importación posterior.
        """
        filas = sales_hourly_rows(day, captured_at, source=source)
        if not filas:
            return 0
        daily_rows = sales_daily_rows(
            day,
            captured_at=captured_at,
            header_date=day.sales_date,
            source=source,
        )
        sales_dates = [row["sales_date"] for row in daily_rows]
        with self._connect() as conn, conn.cursor() as cur:
            self._lock_sales(cur, day.restaurant_id)
            cur.execute(
                "select exists ("
                "select 1 from sales_hourly "
                "where restaurant_id = %s "
                "and (source_date = %s or sales_date = any(%s)) "
                "union all "
                "select 1 from sales_daily_totals "
                "where restaurant_id = %s and sales_date = any(%s)"
                ") as exists",
                (
                    day.restaurant_id,
                    day.sales_date,
                    sales_dates,
                    day.restaurant_id,
                    sales_dates,
                ),
            )
            existing = cur.fetchone()
            if existing and bool(existing.get("exists")):
                return 0
            cur.executemany(
                _insert_if_absent_sql("sales_hourly", _HOURLY_COLUMNS, _HOURLY_KEYS),
                filas,
            )
            self._recompute_sales_days(cur, day, daily_rows, set(sales_dates))
        return len(filas)

    def restaurants_with_hours(self, sales_date: date) -> set[str]:
        """Restaurantes con alguna hora guardada ese día.

        Alimenta el guard del ciclo: un día con horas que vuelve vacío de la fuente de ventas
        es un fallo, no un día sin ventas.
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select distinct restaurant_id from sales_hourly where sales_date = %s",
                (sales_date,),
            )
            return {str(r["restaurant_id"]) for r in cur.fetchall()}

    def existing_sales_days(self, start: date, end: date) -> set[tuple[str, date]]:
        """Qué (restaurante, día) ya tienen horas guardadas en el rango."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select distinct restaurant_id, sales_date from sales_hourly "
                "where sales_date between %s and %s",
                (start, end),
            )
            return {(str(r["restaurant_id"]), r["sales_date"]) for r in cur.fetchall()}

    def earliest_sales_day(self) -> date | None:
        """Primer día con venta guardada, o ``None`` si la base está vacía."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("select min(sales_date) as dia from sales_hourly")
            row = cur.fetchone()
            dia = row["dia"] if row else None
            return dia if isinstance(dia, date) else None

    def incomplete_sales_days(
        self, start: date, end: date, restaurant_ids: tuple[str, ...]
    ) -> list[tuple[str, date]]:
        """Días del rango que hay que recapturar, en orden cronológico.

        Cuatro señales, y ninguna es "tiene pocas horas": los horarios de
        apertura pueden variar entre restaurantes y jornadas.

          1. no hay ninguna hora guardada;
          2. no hay fila de totales, o la tiene con el neto de la fuente de ventas nulo;
          3. la suma horaria no cuadraba con el total de la fuente de ventas;
          4. la última captura es anterior al cierre del día — la grid de la fuente de ventas
             corre de 06:00 a 06:00, así que un día capturado por última vez
             antes de las 06:00 de Madrid del día siguiente quedó a medias por
             definición: le falta como mínimo el remate de su madrugada.
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                with dias as (
                    select r.id as restaurant_id, d::date as sales_date
                    from unnest(%(ids)s::text[]) as r(id)
                    cross join generate_series(%(start)s::date, %(end)s::date, '1 day') as d
                )
                select dias.restaurant_id, dias.sales_date
                from dias
                left join sales_daily_totals t
                       on t.restaurant_id = dias.restaurant_id
                      and t.sales_date = dias.sales_date
                where not exists (
                        select 1 from sales_hourly h
                        where h.restaurant_id = dias.restaurant_id
                          and h.sales_date = dias.sales_date)
                   or t.restaurant_id is null
                   or t.net is null
                   or t.totals_mismatch is not null
                   or (
                        select max(h2.captured_at) from sales_hourly h2
                        where h2.restaurant_id = dias.restaurant_id
                          and h2.sales_date = dias.sales_date
                      ) < timezone(
                        'Europe/Madrid',
                        (dias.sales_date + 1)::timestamp + interval '6 hours'
                      )
                order by dias.sales_date, dias.restaurant_id
                """,
                {"ids": list(restaurant_ids), "start": start, "end": end},
            )
            return [(str(r["restaurant_id"]), r["sales_date"]) for r in cur.fetchall()]

    def upsert_projections(
        self,
        restaurant_id: str,
        sales_date: date,
        projections: list[HourlyProjection],
        *,
        fetched_at: datetime,
        expected_hours: tuple[int, ...],
    ) -> int:
        expected_hours = self._validate_workforce_hours(projections, expected_hours)
        filas = projection_rows(
            restaurant_id,
            sales_date,
            projections,
            fetched_at=fetched_at,
            expected_hours=expected_hours,
        )
        with self._connect() as conn, conn.cursor() as cur:
            self._upsert_complete_workforce_snapshot(
                cur,
                table="workforce_projection_hourly",
                columns=_PROJECTION_COLUMNS,
                restaurant_id=restaurant_id,
                sales_date=sales_date,
                rows=filas,
                expected_hours=expected_hours,
            )
        return len(filas)

    def upsert_staffing(
        self,
        restaurant_id: str,
        sales_date: date,
        staffing: list[HourlyStaffing],
        *,
        fetched_at: datetime,
        expected_hours: tuple[int, ...],
    ) -> int:
        expected_hours = self._validate_workforce_hours(staffing, expected_hours)
        filas = staffing_rows(
            restaurant_id,
            sales_date,
            staffing,
            fetched_at=fetched_at,
            expected_hours=expected_hours,
        )
        with self._connect() as conn, conn.cursor() as cur:
            self._upsert_complete_workforce_snapshot(
                cur,
                table="workforce_staffing_hourly",
                columns=_STAFFING_COLUMNS,
                restaurant_id=restaurant_id,
                sales_date=sales_date,
                rows=filas,
                expected_hours=expected_hours,
            )
        return len(filas)
