"""Fichajes y cuadrante de la fuente de personal, convertidos a intervalos de Madrid.

Los dos feeds NO usan la misma convención de día, y mezclarlas desplaza la
serie sin que salte ningún error:

- **clockguards** viene agrupado por el día de NEGOCIO de la fuente de personal
  e incluye la madrugada que cierra ese día.
- **assignments** viene por día CIVIL, con los tramos en minutos desde la
  medianoche de ``day``; un tramo puede terminar el día civil siguiente.

Aquí los dos se convierten a marcas de tiempo absolutas, que es la única forma
de compararlos hora a hora sin tener que elegir un corte de día.

**Nada de esto identifica a nadie**: se leen códigos internos de empleado, que
sirven para contar personas distintas dentro del worker y no se escriben en
ninguna parte. El endpoint de empleados —que sí trae nombre, correo, fecha de
nacimiento y género— no se toca.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from restaurant_live_ops.tz import MADRID, to_madrid
from restaurant_live_ops.workforce_source.client import WorkforceSourceClient
from restaurant_live_ops.workforce_source.hourly import Interval

TYPE_WORK = "WORK"


def clockguards_path(business_id: str, restaurant_id: str, day: date) -> str:
    """Ruta de los fichajes de un día de negocio."""
    iso = day.isoformat()
    return (
        f"/importer/api/v2/businesses/{business_id}/services/{restaurant_id}"
        f"/clockguards?from={iso}&to={iso}"
    )


def assignments_path(business_id: str, restaurant_id: str, day: date) -> str:
    """Ruta del cuadrante de un día civil."""
    iso = day.isoformat()
    return (
        f"/importer/api/v1/business/{business_id}/service/{restaurant_id}"
        f"/assignments/from/{iso}/to/{iso}"
    )


def _instant(raw: Any) -> datetime | None:
    if not raw:
        return None
    return to_madrid(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))


def parse_clockguards(payload: list[dict[str, Any]]) -> list[Interval]:
    """Fichajes reales. Un ``checkOut`` ausente es un turno todavía abierto."""
    tramos: list[Interval] = []
    for fila in payload:
        if str(fila.get("type")) != TYPE_WORK:
            continue
        entrada = _instant(fila.get("checkIn"))
        if entrada is None:
            continue
        salida = _instant(fila.get("checkOut"))
        # La API devuelve los registros tal como se grabaron: un par mal
        # emparejado puede traer la salida antes que la entrada, y ese tramo
        # negativo restaría presencia de una hora que sí se trabajó.
        if salida is not None and salida <= entrada:
            continue
        tramos.append(Interval(person=str(fila.get("employeeId")), start=entrada, end=salida))
    return tramos


def parse_assignments(payload: list[dict[str, Any]]) -> list[Interval]:
    """Cuadrante. Solo tramos trabajados y pagados de empleados reales."""
    tramos: list[Interval] = []
    for fila in payload:
        if fila.get("virtual"):
            continue
        presencia = fila.get("presence") or {}
        # Un día de descanso llega como un único tramo que cubre el día entero
        # (24 horas, sin pagar): sin este filtro contaría como jornada a
        # cualquier hora y la plantilla asignada saldría disparada.
        if not presencia.get("worked"):
            continue
        dia = date.fromisoformat(str(fila["day"]))
        medianoche = datetime(dia.year, dia.month, dia.day, tzinfo=MADRID)
        for marco in presencia.get("timeFrames") or []:
            if not marco.get("worked") or not marco.get("paid"):
                continue
            duracion = int(marco.get("duration") or 0)
            if duracion <= 0:
                continue
            inicio = medianoche + timedelta(minutes=int(marco.get("startMinuteDay") or 0))
            tramos.append(
                Interval(
                    person=str(fila.get("person")),
                    start=inicio,
                    end=inicio + timedelta(minutes=duracion),
                )
            )
    return tramos


async def fetch_staffing(
    client: WorkforceSourceClient, *, business_id: str, restaurant_id: str, day: date
) -> tuple[list[Interval], list[Interval]]:
    """Fichajes y cuadrante de un restaurante para un día."""
    fichajes = await client.get_json(clockguards_path(business_id, restaurant_id, day))
    cuadrante = await client.get_json(assignments_path(business_id, restaurant_id, day))
    return parse_clockguards(list(fichajes)), parse_assignments(list(cuadrante))
