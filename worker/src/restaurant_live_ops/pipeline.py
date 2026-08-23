"""Ciclo de ingesta: capturar, validar, escribir y dejar constancia.

Regla de oro: un ciclo con cualquier problema termina en estado ``error`` y
con el motivo escrito en ``ingest_runs``, aunque parte de los datos se hayan
guardado. La interfaz enseña esa marca; un fallo silencioso acabaría
produciendo números falsos.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol

from restaurant_live_ops.public_errors import (
    SALES_PUBLIC_ERROR,
    STAFFING_PUBLIC_ERROR,
    WORKFORCE_PUBLIC_ERROR,
)
from restaurant_live_ops.sales_source.parser import (
    FutureSalesError,
    MissingSalesTotalError,
    SalesDay,
    SalesSequenceError,
    SalesTotalsMismatchError,
    validate_publishable_day,
)
from restaurant_live_ops.sales_source.scraper import ScrapeResult
from restaurant_live_ops.workforce_source.hourly import HourlyStaffing, hours_settled_by
from restaurant_live_ops.workforce_source.projections import HourlyProjection

logger = logging.getLogger("restaurant_live_ops.pipeline")

# Reloj por defecto. Se inyecta en los tests, y separa el instante de apertura
# del de cierre: si se estampara el mismo en ambos, la duración registrada
# sería siempre cero y no serviría para vigilar si la cadencia aguanta.
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CycleOutcome:
    status: str  # "ok" | "error"
    rows_written: int
    error: str | None = None


@dataclass(frozen=True)
class SalesCoverage:
    """Pares exactos que una captura puede publicar y sus fallos visibles."""

    days: list[tuple[date, SalesDay]]
    problems: dict[str, list[str]]


def assess_sales_coverage(
    results: list[ScrapeResult],
    accountable_restaurant_ids: tuple[str, ...],
    expected_pairs: set[tuple[str, date]],
    *,
    configured_restaurant_ids: tuple[str, ...] | None = None,
) -> SalesCoverage:
    """Exige una respuesta inequívoca para cada restaurante/fecha esperado.

    Un resultado inesperado no se intenta reinterpretar. Si una respuesta de
    fecha contiene un identificador ajeno a la configuración, se bloquea esa
    fecha completa: publicar solo una parte ocultaría que la navegación quedó
    en un contexto distinto del solicitado.
    """

    problems: dict[str, list[str]] = {
        restaurant_id: [] for restaurant_id in accountable_restaurant_ids
    }
    configured = set(configured_restaurant_ids or accountable_restaurant_ids)
    expected_dates = {sales_date for _, sales_date in expected_pairs}
    expected_restaurant_ids = {restaurant_id for restaurant_id, _ in expected_pairs}
    by_date: dict[date, list[ScrapeResult]] = {}
    for result in results:
        by_date.setdefault(result.sales_date, []).append(result)

    for _unexpected_date in sorted(set(by_date) - expected_dates):
        message = SALES_PUBLIC_ERROR
        for restaurant_id in accountable_restaurant_ids:
            if restaurant_id in expected_restaurant_ids:
                problems[restaurant_id].append(message)

    accepted: list[tuple[date, SalesDay]] = []
    for expected_date in sorted(expected_dates):
        expected_ids = [
            restaurant_id
            for restaurant_id in accountable_restaurant_ids
            if (restaurant_id, expected_date) in expected_pairs
        ]
        captures = by_date.get(expected_date, [])
        if not captures:
            for restaurant_id in expected_ids:
                problems[restaurant_id].append(SALES_PUBLIC_ERROR)
            continue
        if len(captures) != 1:
            for restaurant_id in expected_ids:
                problems[restaurant_id].append(SALES_PUBLIC_ERROR)
            continue

        result = captures[0]
        returned_ids = {day.restaurant_id for day in result.days} | set(result.errors)
        if returned_ids - configured:
            for restaurant_id in expected_ids:
                problems[restaurant_id].append(SALES_PUBLIC_ERROR)
            continue

        for restaurant_id in expected_ids:
            all_days = [day for day in result.days if day.restaurant_id == restaurant_id]
            matching_days = [day for day in all_days if day.sales_date == expected_date]
            source_error = result.errors.get(restaurant_id)

            if source_error is not None and all_days:
                problems[restaurant_id].append(SALES_PUBLIC_ERROR)
            elif any(day.sales_date != expected_date for day in all_days):
                problems[restaurant_id].append(SALES_PUBLIC_ERROR)
            elif len(matching_days) > 1:
                problems[restaurant_id].append(SALES_PUBLIC_ERROR)
            elif source_error is not None:
                problems[restaurant_id].append(SALES_PUBLIC_ERROR)
            elif not matching_days:
                problems[restaurant_id].append(SALES_PUBLIC_ERROR)
            else:
                accepted.append((expected_date, matching_days[0]))

    return SalesCoverage(days=accepted, problems=problems)


class SupportsRuns(Protocol):
    def start_run(self, source: str, restaurant_id: str, *, started_at: datetime) -> int: ...

    def finish_run(
        self,
        run_id: int,
        *,
        finished_at: datetime,
        status: str,
        rows_written: int = 0,
        error: str | None = None,
    ) -> None: ...


class SalesSink(SupportsRuns, Protocol):
    def upsert_sales_day(
        self,
        day: SalesDay,
        *,
        captured_at: datetime,
        header_date: date | None,
        source: str = "live",
    ) -> int: ...

    def insert_sales_day_if_absent(
        self,
        day: SalesDay,
        *,
        captured_at: datetime,
        source: str,
    ) -> int: ...

    def restaurants_with_hours(self, sales_date: date) -> set[str]: ...


class ProjectionSink(SupportsRuns, Protocol):
    def upsert_projections(
        self,
        restaurant_id: str,
        sales_date: date,
        projections: list[HourlyProjection],
        *,
        fetched_at: datetime,
        expected_hours: tuple[int, ...],
    ) -> int: ...


class StaffingSink(SupportsRuns, Protocol):
    def upsert_staffing(
        self,
        restaurant_id: str,
        sales_date: date,
        staffing: list[HourlyStaffing],
        *,
        fetched_at: datetime,
        expected_hours: tuple[int, ...],
    ) -> int: ...


async def run_sales_cycle(
    scraper: Callable[[], Awaitable[ScrapeResult]],
    db: SalesSink,
    restaurant_ids: tuple[str, ...],
    *,
    clock: Clock = _utc_now,
) -> CycleOutcome:
    """Compatibilidad para una sola fecha de caja."""

    async def batch() -> list[ScrapeResult]:
        return [await scraper()]

    return await run_sales_batch_cycle(batch, db, restaurant_ids, clock=clock)


async def run_sales_batch_cycle(
    scraper: Callable[[], Awaitable[list[ScrapeResult]]],
    db: SalesSink,
    restaurant_ids: tuple[str, ...],
    *,
    clock: Clock = _utc_now,
    source: str = "live",
    run_source: str = "sales",
    write_mode: Literal["replace", "insert_only"] = "replace",
    expected_dates: tuple[date, ...] | None = None,
) -> CycleOutcome:
    """Captura una o varias fechas de caja en un único ciclo auditado.

    Alrededor del relevo de caja, ayer y hoy pueden estar activos a la vez en
    restaurantes distintos. Ambos resultados comparten login y ciclo, pero se
    validan y publican por separado: un fallo en uno no bloquea el otro.
    """
    inicio = clock()
    run_ids = {
        restaurant_id: db.start_run(run_source, restaurant_id, started_at=inicio)
        for restaurant_id in restaurant_ids
    }
    problemas: dict[str, list[str]] = {restaurant_id: [] for restaurant_id in restaurant_ids}
    escritas: dict[str, int] = {restaurant_id: 0 for restaurant_id in restaurant_ids}

    def fail_all(message: str, *, finished_at: datetime) -> CycleOutcome:
        for restaurant_id, run_id in run_ids.items():
            db.finish_run(
                run_id,
                finished_at=finished_at,
                status="error",
                rows_written=escritas[restaurant_id],
                error=message,
            )
        return CycleOutcome(status="error", rows_written=sum(escritas.values()), error=message)

    try:
        resultados = await scraper()
    except Exception:
        # Se registra y se devuelve como error del ciclo: nunca se traga.
        mensaje = SALES_PUBLIC_ERROR
        logger.error("la fuente de ventas: ciclo fallido: %s", mensaje)
        return fail_all(mensaje, finished_at=clock())

    if not resultados:
        mensaje = SALES_PUBLIC_ERROR
        logger.error("la fuente de ventas: ciclo fallido: %s", mensaje)
        return fail_all(mensaje, finished_at=clock())

    # La captura acaba de terminar: este es el instante que marca su frescura.
    fin = clock()

    target_dates = expected_dates or tuple(dict.fromkeys(r.sales_date for r in resultados))
    coverage = assess_sales_coverage(
        resultados,
        restaurant_ids,
        {(restaurant_id, target) for restaurant_id in restaurant_ids for target in target_dates},
    )
    problemas = coverage.problems

    for header_date, day in coverage.days:
        if not day.hours:
            problemas[day.restaurant_id].append(SALES_PUBLIC_ERROR)
            continue
        try:
            validate_publishable_day(day, now=fin)
        except (
            MissingSalesTotalError,
            SalesTotalsMismatchError,
            SalesSequenceError,
            FutureSalesError,
        ):
            problemas[day.restaurant_id].append(SALES_PUBLIC_ERROR)
            continue
        if write_mode == "insert_only":
            escritas[day.restaurant_id] += db.insert_sales_day_if_absent(
                day,
                captured_at=fin,
                source=source,
            )
        else:
            escritas[day.restaurant_id] += db.upsert_sales_day(
                day,
                captured_at=fin,
                header_date=header_date,
                source=source,
            )

    problemas_ciclo = [motivo for rid in restaurant_ids for motivo in problemas[rid]]
    for restaurant_id, run_id in run_ids.items():
        errores = problemas[restaurant_id]
        db.finish_run(
            run_id,
            finished_at=fin,
            status="error" if errores else "ok",
            rows_written=escritas[restaurant_id],
            error=SALES_PUBLIC_ERROR if errores else None,
        )

    if problemas_ciclo:
        mensaje = SALES_PUBLIC_ERROR
        logger.error("la fuente de ventas: ciclo con problemas: %s", mensaje)
        return CycleOutcome(status="error", rows_written=sum(escritas.values()), error=mensaje)

    return CycleOutcome(status="ok", rows_written=sum(escritas.values()))


async def run_workforce_cycle(
    fetcher: Callable[[str], Awaitable[list[HourlyProjection]]],
    db: ProjectionSink,
    restaurant_ids: tuple[str, ...],
    sales_date: date,
    *,
    expected_hours_by_restaurant: Mapping[str, tuple[int, ...]],
    clock: Clock = _utc_now,
) -> CycleOutcome:
    """Refresca la previsión del día de los restaurantes indicados."""
    inicio = clock()
    run_ids = {
        restaurant_id: db.start_run("workforce", restaurant_id, started_at=inicio)
        for restaurant_id in restaurant_ids
    }
    problemas: dict[str, str] = {}
    escritas: dict[str, int] = {restaurant_id: 0 for restaurant_id in restaurant_ids}

    for restaurant_id in restaurant_ids:
        try:
            previsiones = await fetcher(restaurant_id)
            expected_hours = expected_hours_by_restaurant.get(restaurant_id, ())
            if not _has_exact_expected_hours(previsiones, expected_hours):
                problemas[restaurant_id] = WORKFORCE_PUBLIC_ERROR
                continue
            escritas[restaurant_id] += db.upsert_projections(
                restaurant_id,
                sales_date,
                previsiones,
                fetched_at=clock(),
                expected_hours=expected_hours,
            )
        except Exception:
            # Un local caído no debe tumbar a los otros dos.
            problemas[restaurant_id] = WORKFORCE_PUBLIC_ERROR
            continue

    fin = clock()
    for restaurant_id, run_id in run_ids.items():
        error = problemas.get(restaurant_id)
        db.finish_run(
            run_id,
            finished_at=fin,
            status="error" if error else "ok",
            rows_written=escritas[restaurant_id],
            error=error,
        )

    if problemas:
        mensaje = WORKFORCE_PUBLIC_ERROR
        logger.error("la fuente de personal: ciclo con problemas: %s", mensaje)
        return CycleOutcome(status="error", rows_written=sum(escritas.values()), error=mensaje)

    return CycleOutcome(status="ok", rows_written=sum(escritas.values()))


# Margen antes de usar una hora cerrada como señal de feed caído. Los marcajes
# pueden llegar con retraso; las horas recientes no deben crear falsos fallos.
# Una ausencia persistente en horas ya asentadas sigue haciendo fallar el ciclo.
LATE_PUNCH_GRACE = timedelta(hours=2)


def _has_exact_expected_hours(
    rows: Sequence[HourlyProjection] | Sequence[HourlyStaffing],
    expected_hours: tuple[int, ...],
) -> bool:
    if (
        not expected_hours
        or len(set(expected_hours)) != len(expected_hours)
        or any(type(hour) is not int or hour < 0 or hour > 23 for hour in expected_hours)
    ):
        return False
    actual_hours = [row.hour for row in rows]
    return len(actual_hours) == len(expected_hours) and set(actual_hours) == set(expected_hours)


async def run_staffing_cycle(
    fetcher: Callable[[str, date], Awaitable[list[HourlyStaffing]]],
    db: StaffingSink,
    restaurant_ids: tuple[str, ...],
    sales_date: date,
    *,
    expected_hours_by_restaurant: Mapping[str, tuple[int, ...]],
    clock: Clock = _utc_now,
) -> CycleOutcome:
    """Refresca el personal fichado y asignado del día."""
    inicio = clock()
    run_ids = {
        restaurant_id: db.start_run("staffing", restaurant_id, started_at=inicio)
        for restaurant_id in restaurant_ids
    }
    problemas: dict[str, str] = {}
    escritas: dict[str, int] = {restaurant_id: 0 for restaurant_id in restaurant_ids}

    for restaurant_id in restaurant_ids:
        try:
            filas = await fetcher(restaurant_id, sales_date)
        except Exception:
            # Un local caído no debe tumbar a los otros dos.
            problemas[restaurant_id] = STAFFING_PUBLIC_ERROR
            continue

        expected_hours = expected_hours_by_restaurant.get(restaurant_id, ())
        if not _has_exact_expected_hours(filas, expected_hours):
            problemas[restaurant_id] = STAFFING_PUBLIC_ERROR
            continue

        # Turnos asignados y CERO fichajes en horas que ya deberían estar
        # resueltas no es "no fue nadie a trabajar": es el feed de fichajes
        # caído. Escribir ceros publicaría una plantilla vacía que no ha
        # existido. Un solo fichaje en cualquier hora del día basta para saber
        # que la fuente responde, así que solo la ausencia total acusa.
        pasadas = [f for f in filas if f.clocked_count is not None]
        asentadas = hours_settled_by(sales_date, inicio - LATE_PUNCH_GRACE)
        hubo_asignaciones = any(f.assigned_count > 0 for f in pasadas if f.hour in asentadas)
        hubo_fichajes = any((f.clocked_count or 0) > 0 for f in pasadas)
        if hubo_asignaciones and not hubo_fichajes:
            problemas[restaurant_id] = STAFFING_PUBLIC_ERROR
            continue

        try:
            escritas[restaurant_id] += db.upsert_staffing(
                restaurant_id,
                sales_date,
                filas,
                fetched_at=clock(),
                expected_hours=expected_hours,
            )
        except Exception:
            problemas[restaurant_id] = STAFFING_PUBLIC_ERROR

    fin = clock()
    for restaurant_id, run_id in run_ids.items():
        error = problemas.get(restaurant_id)
        db.finish_run(
            run_id,
            finished_at=fin,
            status="error" if error else "ok",
            rows_written=escritas[restaurant_id],
            error=error,
        )

    if problemas:
        mensaje = STAFFING_PUBLIC_ERROR
        logger.error("Personal: ciclo con problemas: %s", mensaje)
        return CycleOutcome(status="error", rows_written=sum(escritas.values()), error=mensaje)

    return CycleOutcome(status="ok", rows_written=sum(escritas.values()))
