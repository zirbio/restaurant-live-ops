"""Recuperación de los días que faltan o quedaron incompletos.

Corre una vez al día de madrugada, con los locales cerrados: no es el ciclo
del día en curso y no debe competir con él por la fuente de ventas. Deja su propio rastro en
``ingest_runs`` (``sales_backfill``) para no ensuciar el indicador de frescura.

El criterio de aceptación es el mismo de siempre: una captura que no cuadra
con la fila de totales de la fuente de ventas NO se guarda. El hueco se queda y mañana se
vuelve a intentar.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Protocol

from restaurant_live_ops.pipeline import (
    Clock,
    CycleOutcome,
    SupportsRuns,
    assess_sales_coverage,
)
from restaurant_live_ops.public_errors import BACKFILL_PUBLIC_ERROR
from restaurant_live_ops.sales_source.parser import (
    FutureSalesError,
    MissingSalesTotalError,
    SalesDay,
    SalesSequenceError,
    SalesTotalsMismatchError,
    validate_publishable_day,
)
from restaurant_live_ops.sales_source.scraper import ScrapeResult

logger = logging.getLogger("restaurant_live_ops.backfill")

SOURCE = "sales_backfill"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class BackfillSink(SupportsRuns, Protocol):
    """Superficie mínima que necesita la recaptura histórica."""

    def restaurants_with_hours(self, sales_date: date) -> set[str]: ...

    def upsert_sales_day(
        self,
        day: SalesDay,
        *,
        captured_at: datetime,
        header_date: date | None,
        source: str = "live",
    ) -> int: ...


def days_to_recapture(gaps: list[tuple[str, date]]) -> list[date]:
    """Los días distintos que hay que visitar, en orden cronológico.

    Una sola visita trae todos los restaurantes, así que se agrupa por día para
    no multiplicar peticiones equivalentes.
    """
    return sorted({d for _, d in gaps})


async def run_backfill_cycle(
    gaps: list[tuple[str, date]],
    scraper: Callable[[date], Awaitable[ScrapeResult]],
    db: BackfillSink,
    *,
    clock: Clock = _utc_now,
    configured_restaurant_ids: tuple[str, ...] | None = None,
) -> CycleOutcome:
    """Recaptura los días con hueco y los guarda si cuadran."""
    dias = days_to_recapture(gaps)
    if not dias:
        return CycleOutcome(status="ok", rows_written=0)

    inicio = clock()
    restaurant_ids = tuple(sorted({restaurant_id for restaurant_id, _ in gaps}))
    requested = set(gaps)
    run_ids = {
        restaurant_id: db.start_run(SOURCE, restaurant_id, started_at=inicio)
        for restaurant_id in restaurant_ids
    }
    problemas: dict[str, list[str]] = {restaurant_id: [] for restaurant_id in restaurant_ids}
    escritas: dict[str, int] = {restaurant_id: 0 for restaurant_id in restaurant_ids}

    logger.info("backfill: %d días por recuperar", len(dias))

    for dia in dias:
        try:
            resultado = await scraper(dia)
        except Exception:
            # Un día que falla no debe impedir recuperar los demás.
            for restaurant_id in restaurant_ids:
                if (restaurant_id, dia) in requested:
                    problemas[restaurant_id].append(BACKFILL_PUBLIC_ERROR)
            logger.error("backfill: una fecha falló: %s", BACKFILL_PUBLIC_ERROR)
            continue

        expected_for_day = {
            (restaurant_id, dia)
            for restaurant_id in restaurant_ids
            if (restaurant_id, dia) in requested
        }
        coverage = assess_sales_coverage(
            [resultado],
            restaurant_ids,
            expected_for_day,
            configured_restaurant_ids=configured_restaurant_ids,
        )
        for restaurant_id, messages in coverage.problems.items():
            problemas[restaurant_id].extend(messages)

        for header_date, day in coverage.days:
            if not day.hours:
                problemas[day.restaurant_id].append(BACKFILL_PUBLIC_ERROR)
                continue
            try:
                validate_publishable_day(day, now=None)
            except (
                MissingSalesTotalError,
                SalesTotalsMismatchError,
                SalesSequenceError,
                FutureSalesError,
            ):
                problemas[day.restaurant_id].append(BACKFILL_PUBLIC_ERROR)
                continue
            escritas[day.restaurant_id] += db.upsert_sales_day(
                day, captured_at=clock(), header_date=header_date, source="backfill"
            )

    fin = clock()
    for restaurant_id, run_id in run_ids.items():
        errores = problemas[restaurant_id]
        db.finish_run(
            run_id,
            finished_at=fin,
            status="error" if errores else "ok",
            rows_written=escritas[restaurant_id],
            error=BACKFILL_PUBLIC_ERROR if errores else None,
        )

    problemas_ciclo = [motivo for rid in restaurant_ids for motivo in problemas[rid]]
    if problemas_ciclo:
        mensaje = BACKFILL_PUBLIC_ERROR
        logger.error("backfill: ciclo con problemas: %s", mensaje)
        return CycleOutcome(status="error", rows_written=sum(escritas.values()), error=mensaje)

    return CycleOutcome(status="ok", rows_written=sum(escritas.values()))
