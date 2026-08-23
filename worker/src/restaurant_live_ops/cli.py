"""Puntos de entrada del worker.

Cada comando representa una fuente y devuelve código 1 si el ciclo tuvo
cualquier problema, para que el programador de tareas lo vea.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, date, datetime, timedelta

from restaurant_live_ops.backfill import run_backfill_cycle
from restaurant_live_ops.config import (
    DbSettings,
    SalesSourceSettings,
    StaffingSettings,
    WorkforceSourceSettings,
)
from restaurant_live_ops.db import Database
from restaurant_live_ops.logging_config import configure_logging
from restaurant_live_ops.pipeline import (
    CycleOutcome,
    run_sales_batch_cycle,
    run_staffing_cycle,
    run_workforce_cycle,
)
from restaurant_live_ops.public_errors import WORKFORCE_PUBLIC_ERROR, public_error_for_source
from restaurant_live_ops.restaurants import restaurants_from_env
from restaurant_live_ops.sales_source.scraper import ScrapeResult, scrape_day, scrape_days
from restaurant_live_ops.tz import (
    BUSINESS_DAY_CUTOFF_HOUR,
    MADRID,
    business_date,
    days_between,
    now_madrid,
    today_madrid,
)
from restaurant_live_ops.workforce_source.client import WorkforceSourceClient
from restaurant_live_ops.workforce_source.hourly import HourlyStaffing, Interval, hourly_staffing
from restaurant_live_ops.workforce_source.projections import HourlyProjection, fetch_projections
from restaurant_live_ops.workforce_source.roles import (
    fetch_named_exclusions,
    fetch_person_categories,
    resolve_crew,
)
from restaurant_live_ops.workforce_source.staffing import fetch_staffing

logger = logging.getLogger("restaurant_live_ops")


# La ventana conserva el día anterior hasta una hora de sellado común. Así un
# ciclo fallido durante un relevo asíncrono no deja sin recoger la cola final.
_SALES_SOURCE_SEAL_ENDS_AT = 13


def sales_cycle_targets(now: datetime) -> list[date]:
    """Fechas la fuente de ventas que pueden seguir cambiando en este instante.

    La fecha de caja no es el día operativo 06→06. Durante la ventana de
    relevo se capturan ayer y hoy en una sola sesión porque cada restaurante
    puede cambiar de fecha en un momento distinto. Tras el sellado, solo hoy
    puede cambiar.
    """
    local = now.astimezone(MADRID)
    today = local.date()
    if local.hour < _SALES_SOURCE_SEAL_ENDS_AT:
        return [today - timedelta(days=1), today]
    return [today]


def recapture_batches(start: date, end: date, *, size: int = 7) -> list[list[date]]:
    """Divide una recaptura amplia en sesiones de navegador acotadas."""
    if size <= 0:
        raise ValueError("el tamaño del lote debe ser positivo")
    days = days_between(start, end)
    return [days[index : index + size] for index in range(0, len(days), size)]


# Hasta esta hora de Madrid, los primeros ciclos del día repasan también el
# día recién cerrado: el último ciclo de la madrugada se queda a minutos del
# corte de las 06:00 y la cola final de fichajes quedaría sin recoger.
_MORNING_SEAL_ENDS_AT = 9


def cycle_targets(now: datetime) -> list[date]:
    """Los días de negocio que un ciclo de la fuente de personal debe refrescar ahora.

    Siempre el día vivo (que de madrugada es ayer). A primera hora de la
    mañana, además, el recién cerrado: el personal, para sellarlo con sus
    fichajes completos; la previsión, por si la madrugada final no estaba
    cargada aún en la fuente de personal cuando se pidió la víspera.
    """
    vivo = business_date(now)
    hora = now.astimezone(MADRID).hour
    if BUSINESS_DAY_CUTOFF_HOUR <= hora < _MORNING_SEAL_ENDS_AT:
        return [vivo, vivo - timedelta(days=1)]
    return [vivo]


def _report(source: str, outcome: CycleOutcome) -> int:
    logger.info("ciclo %s: %s (%d filas)", source, outcome.status, outcome.rows_written)
    if outcome.error:
        logger.error("ciclo %s con problemas: %s", source, public_error_for_source(source))
    return 0 if outcome.status == "ok" else 1


async def _sales() -> int:
    db = Database(DbSettings.from_env().url)
    settings = SalesSourceSettings.from_env()
    restaurants = restaurants_from_env()
    targets = sales_cycle_targets(datetime.now(UTC))
    outcome = await run_sales_batch_cycle(
        lambda: scrape_days(settings, targets, restaurants=restaurants),
        db,
        tuple(restaurant.id for restaurant in restaurants),
        expected_dates=tuple(targets),
    )
    return _report("la fuente de ventas", outcome)


async def _recapture_sales(desde: date, hasta: date) -> int:
    """Recaptura explícita append-only de fechas la fuente de ventas ya cerradas."""
    if hasta < desde:
        logger.error("recaptura la fuente de ventas: el final es anterior al inicio")
        return 1
    if hasta >= today_madrid():
        logger.error("recaptura la fuente de ventas: %s aún no es una fecha de caja cerrada", hasta)
        return 1

    db = Database(DbSettings.from_env().url)
    settings = SalesSourceSettings.from_env()
    restaurants = restaurants_from_env()
    code = 0
    for batch in recapture_batches(desde, hasta):

        async def capture(current: list[date] = batch) -> list[ScrapeResult]:
            return await scrape_days(
                settings,
                current,
                restaurants=restaurants,
            )

        outcome = await run_sales_batch_cycle(
            capture,
            db,
            tuple(restaurant.id for restaurant in restaurants),
            source="backfill",
            run_source="sales_backfill",
            write_mode="insert_only",
            expected_dates=tuple(batch),
        )
        code = max(code, _report("la fuente de ventas recapture", outcome))
    return code


async def _workforce() -> int:
    """Previsión del día de negocio vivo (y, por la mañana, la de ayer)."""
    db = Database(DbSettings.from_env().url)
    settings = WorkforceSourceSettings.from_env()
    restaurants = restaurants_from_env()
    client = WorkforceSourceClient(settings)
    ahora = now_madrid()

    codigo = 0
    try:
        for dia in cycle_targets(ahora):

            async def fetcher(restaurant_id: str, dia: date = dia) -> list[HourlyProjection]:
                return await fetch_projections(
                    client,
                    business_id=settings.business_id,
                    restaurant_id=restaurant_id,
                    day=dia,
                )

            outcome = await run_workforce_cycle(
                fetcher,
                db,
                tuple(r.id for r in restaurants),
                dia,
                expected_hours_by_restaurant={
                    restaurant.id: restaurant.workforce_expected_hours for restaurant in restaurants
                },
            )
            codigo = max(codigo, _report("la fuente de personal", outcome))
    finally:
        await client.aclose()
    return codigo


async def _staffing() -> int:
    """Personal fichado y asignado del día de negocio VIVO.

    De madrugada, el día vivo es ayer: los fichajes del turno de cierre deben
    caer en la rejilla del día al que pertenece esa noche, junto a su venta.
    """
    db = Database(DbSettings.from_env().url)
    settings = WorkforceSourceSettings.from_env()
    restaurants = restaurants_from_env()
    staffing_settings = StaffingSettings.from_env()
    client = WorkforceSourceClient(settings)
    ahora = now_madrid()

    # Las exclusiones nominales se resuelven una vez por ciclo y por
    # restaurante, no una por día: la ficha de una persona no cambia entre el
    # día vivo y el que se está sellando.
    exclusiones: dict[str, set[str]] = {}

    async def excluidos(restaurant_id: str) -> set[str]:
        if restaurant_id not in exclusiones:
            codigos, sin_casar = await fetch_named_exclusions(
                client,
                business_id=settings.business_id,
                restaurant_id=restaurant_id,
                names=staffing_settings.excluded_people,
            )
            if sin_casar:
                # la fuente de personal reescribe fichas: una exclusión que deja de casar
                # devolvería a esa persona al recuento sin que nadie se entere.
                # Solo la posición del nombre en la lista, nunca el nombre.
                logger.warning(
                    "Personal: %s tiene %d exclusión(es) nominal(es) sin resolver (posiciones %s)",
                    restaurant_id,
                    len(sin_casar),
                    ", ".join(str(i) for i in sin_casar),
                )
            exclusiones[restaurant_id] = codigos
        return exclusiones[restaurant_id]

    async def fetcher(restaurant_id: str, dia: date) -> list[HourlyStaffing]:
        # La rejilla del día de negocio (06:00 → 06:00) cruza hasta tres días
        # de la fuente de personal: los fichajes van agrupados con frontera en las 02:00 —la
        # madrugada final del día D cae en el día D+1 de la fuente de personal, y un turno
        # que entra antes de las 06:00 de D viene en el D-1— y el cuadrante es
        # civil, con tramos que rebasan la medianoche. Los tramos que caen
        # fuera de la rejilla no suman: pedir de más no ensucia.
        fichajes: list[Interval] = []
        cuadrante: list[Interval] = []
        for pedido in (dia - timedelta(days=1), dia, dia + timedelta(days=1)):
            f, c = await fetch_staffing(
                client,
                business_id=settings.business_id,
                restaurant_id=restaurant_id,
                day=pedido,
            )
            fichajes.extend(f)
            cuadrante.extend(c)

        # El rol no viaja con el fichaje: hay que pedir el contrato vigente de
        # cada persona. Se consultan solo las que aparecen en la captura y no
        # se guarda ninguna identidad.
        presentes = [i.person for i in fichajes] + [i.person for i in cuadrante]
        fuera = await excluidos(restaurant_id)
        categorias = await fetch_person_categories(
            client,
            business_id=settings.business_id,
            people=[p for p in presentes if p not in fuera],
            on=dia,
        )
        equipo, sin_clasificar = resolve_crew(categorias, people=presentes, excluded=fuera)
        if sin_clasificar:
            logger.warning(
                "Personal: %s con %d persona(s) sin categoría vigente el %s; "
                "el día se guarda sin recuento de equipo",
                restaurant_id,
                sin_clasificar,
                dia,
            )
        return hourly_staffing(fichajes, cuadrante, day=dia, now=ahora, crew=equipo)

    codigo = 0
    try:
        for dia in cycle_targets(ahora):
            outcome = await run_staffing_cycle(
                fetcher,
                db,
                tuple(r.id for r in restaurants),
                dia,
                expected_hours_by_restaurant={
                    restaurant.id: restaurant.workforce_expected_hours for restaurant in restaurants
                },
            )
            codigo = max(codigo, _report("Personal", outcome))
    finally:
        await client.aclose()
    return codigo


async def _backfill(dias: int) -> int:
    """Recupera los huecos de los últimos ``dias`` días, sin contar hoy.

    Hoy se excluye a propósito: está a medias por definición y su ciclo normal
    lo va completando cada doce minutos. Meterlo aquí lo marcaría como hueco
    todas las noches.
    """
    db = Database(DbSettings.from_env().url)
    settings = SalesSourceSettings.from_env()
    restaurants = restaurants_from_env()
    hasta = today_madrid() - timedelta(days=1)
    desde = hasta - timedelta(days=dias - 1)

    # La ventana no puede excavar antes del histórico: allí no hay huecos que
    # tapar, solo días que nunca existieron en esta base. Sin este tope, un
    # `--days` generoso amplía el histórico en silencio y mueve el primer día
    # que la app ofrece en el selector.
    primero = db.earliest_sales_day()
    if primero is not None and desde < primero:
        logger.info("backfill: la ventana empezaba en %s; se acota a %s", desde, primero)
        desde = primero

    huecos = db.incomplete_sales_days(desde, hasta, tuple(r.id for r in restaurants))
    outcome = await run_backfill_cycle(
        huecos,
        lambda dia: scrape_day(settings, dia, restaurants=restaurants),
        db,
        configured_restaurant_ids=tuple(r.id for r in restaurants),
    )
    return _report("la fuente de ventas backfill", outcome)


async def _workforce_backfill(desde: date, hasta: date) -> int:
    """Repide la previsión de días pasados, un día y un restaurante por llamada.

    la fuente de personal devuelve la previsión TAL COMO QUEDÓ GUARDADA, que no tiene por qué
    ser la que se veía aquella mañana. Es la única disponible, y por eso queda
    dicho aquí y en la interfaz.

    Un día que falle no tumba a los demás: se cuenta y se informa al final. Sin
    previsión, la app ya sabe decir que no se puede comparar.
    """
    db = Database(DbSettings.from_env().url)
    settings = WorkforceSourceSettings.from_env()
    restaurants = restaurants_from_env()
    client = WorkforceSourceClient(settings)
    escritas = 0
    fallos = 0

    try:
        for dia in days_between(desde, hasta):
            for restaurante in restaurants:
                try:
                    previsiones = await fetch_projections(
                        client,
                        business_id=settings.business_id,
                        restaurant_id=restaurante.id,
                        day=dia,
                    )
                except Exception:
                    fallos += 1
                    continue
                escritas += db.upsert_projections(
                    restaurante.id,
                    dia,
                    previsiones,
                    fetched_at=datetime.now(UTC),
                    expected_hours=restaurante.workforce_expected_hours,
                )
            logger.info(
                "fuente de personal backfill: %s hecho (%d filas acumuladas)",
                dia,
                escritas,
            )
    finally:
        await client.aclose()

    logger.info(
        "fuente de personal backfill %s → %s: %d filas, %d fallos",
        desde,
        hasta,
        escritas,
        fallos,
    )
    if fallos:
        logger.error("la fuente de personal backfill: %s", WORKFORCE_PUBLIC_ERROR)
    return 0 if fallos == 0 else 1


def _parse_day(raw: str) -> date:
    return date.fromisoformat(raw)


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="restaurant-live-ops-worker")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sales", help="venta del día en curso")
    sub.add_parser("workforce", help="previsión del día en curso")
    sub.add_parser("staffing", help="personal fichado y asignado del día en curso")

    workforce_bf = sub.add_parser(
        "workforce-backfill", help="repite la previsión de un rango de días pasados"
    )
    workforce_bf.add_argument("--from", dest="desde", type=_parse_day, required=True)
    workforce_bf.add_argument("--to", dest="hasta", type=_parse_day, required=True)

    recuperar = sub.add_parser("backfill", help="recupera los días que faltan o descuadran")
    recuperar.add_argument("--days", dest="dias", type=int, default=14)

    recapturar = sub.add_parser(
        "sales-recapture",
        help="recaptura de forma append-only un rango cerrado de fechas de venta",
    )
    recapturar.add_argument("--from", dest="desde", type=_parse_day, required=True)
    recapturar.add_argument("--to", dest="hasta", type=_parse_day, required=True)

    args = parser.parse_args()
    if args.command == "sales":
        return asyncio.run(_sales())
    if args.command == "workforce":
        return asyncio.run(_workforce())
    if args.command == "staffing":
        return asyncio.run(_staffing())
    if args.command == "workforce-backfill":
        return asyncio.run(_workforce_backfill(args.desde, args.hasta))
    if args.command == "backfill":
        return asyncio.run(_backfill(args.dias))
    if args.command == "sales-recapture":
        return asyncio.run(_recapture_sales(args.desde, args.hasta))
    raise AssertionError(f"comando no manejado: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
