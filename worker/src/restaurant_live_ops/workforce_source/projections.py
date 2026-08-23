"""Previsión de venta y guest counts de la fuente de personal, por horas del día de NEGOCIO.

El endpoint devuelve intervalos de 15 minutos con marcas de tiempo en UTC
(sufijo ``Z``). Agruparlos sin convertir desplaza la curva una o dos horas
según la época del año, y el síntoma aparece lejos de la causa. Aquí se
convierte a Madrid antes de agrupar.

El día que la fuente de personal entiende en ``from``/``to`` es CIVIL, pero la
rejilla que se guarda es el día de NEGOCIO: la previsión de la hora
1 del día D es la de la madrugada que CIERRA D, y debe leerse al lado de la
venta de esa misma noche. Por eso un día de negocio exige dos peticiones: la
suya y la del civil siguiente, de donde sale su madrugada.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from restaurant_live_ops.tz import business_date, to_madrid
from restaurant_live_ops.workforce_source.client import WorkforceSourceClient

MEASURE_SALES = "VENTA"
MEASURE_GUEST_COUNTS = "GCS"


@dataclass(frozen=True)
class HourlyProjection:
    hour: int
    sales: Decimal
    guest_counts: Decimal


def projections_path(business_id: str, restaurant_id: str, day: date) -> str:
    """Ruta del endpoint de proyecciones para un día.

    Ojo: el segmento ``product`` lleva el ID del restaurante, no un producto.
    """
    iso = day.isoformat()
    return (
        f"/importer/api/v1/business/{business_id}/product/{restaurant_id}"
        f"/projections/from/{iso}/to/{iso}"
    )


def aggregate_projections(
    intervals: list[dict[str, Any]], *, target_day: date
) -> list[HourlyProjection]:
    """Agrega los intervalos de 15 minutos en las horas del día de NEGOCIO."""
    ventas: dict[int, Decimal] = defaultdict(lambda: Decimal(0))
    gcs: dict[int, Decimal] = defaultdict(lambda: Decimal(0))

    for item in intervals:
        measure = item.get("measure")
        if measure not in (MEASURE_SALES, MEASURE_GUEST_COUNTS):
            continue
        inicio = to_madrid(datetime.fromisoformat(str(item["from"]).replace("Z", "+00:00")))
        if business_date(inicio) != target_day:
            continue
        valor = Decimal(str(item["value"]))
        if measure == MEASURE_SALES:
            ventas[inicio.hour] += valor
        else:
            gcs[inicio.hour] += valor

    return [
        HourlyProjection(
            hour=h,
            sales=ventas.get(h, Decimal(0)),
            guest_counts=gcs.get(h, Decimal(0)),
        )
        for h in sorted(set(ventas) | set(gcs))
    ]


async def fetch_projections(
    client: WorkforceSourceClient, *, business_id: str, restaurant_id: str, day: date
) -> list[HourlyProjection]:
    """Descarga y agrega la previsión de un restaurante para un día de NEGOCIO.

    Dos peticiones: la madrugada que cierra ``day`` vive en el día civil
    siguiente de la fuente de personal. Los intervalos que caen fuera del día de negocio se
    descartan al agregar.
    """
    datos = await client.get_json(projections_path(business_id, restaurant_id, day))
    siguiente = await client.get_json(
        projections_path(business_id, restaurant_id, day + timedelta(days=1))
    )
    return aggregate_projections(list(datos) + list(siguiente), target_day=day)
