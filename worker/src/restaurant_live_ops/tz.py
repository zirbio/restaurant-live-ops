"""Fechas y horas de negocio, siempre en Europe/Madrid.

El worker puede correr en UTC: calcular "hoy" con el reloj del servidor daría
el día equivocado de madrugada. Todo lo que sea una fecha de negocio pasa por
aquí.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")

# Lo anterior a esta hora pertenece al día operativo ANTERIOR. Es el corte
# común elegido para comparar venta, personal, previsión y horas. No describe
# la fecha de caja de la fuente de ventas, cuyo relevo puede variar.
BUSINESS_DAY_CUTOFF_HOUR = 6


def now_madrid(*, now: datetime | None = None) -> datetime:
    """Instante actual en Madrid. ``now`` permite inyectarlo en los tests."""
    momento = now if now is not None else datetime.now(UTC)
    return to_madrid(momento)


def today_madrid(*, now: datetime | None = None) -> date:
    """El día civil de hoy en una ubicación local."""
    return now_madrid(now=now).date()


def to_madrid(dt: datetime) -> datetime:
    """Convierte un instante con zona horaria a hora de Madrid."""
    if dt.tzinfo is None:
        raise ValueError("datetime sin zona horaria: no se puede convertir a Madrid")
    return dt.astimezone(MADRID)


def days_between(start: date, end: date) -> list[date]:
    """Todos los días del rango, extremos incluidos.

    Se cuenta por días de calendario, no sumando 24 horas: marzo tiene un día
    de 23 horas y octubre uno de 25.
    """
    if end < start:
        return []
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def business_date(dt: datetime) -> date:
    """Día de negocio del instante dado, con corte a las 06:00 de Madrid."""
    local = to_madrid(dt)
    if local.hour < BUSINESS_DAY_CUTOFF_HOUR:
        return (local - timedelta(days=1)).date()
    return local.date()


def business_day_order(hour: int) -> int:
    """Posición de una hora dentro del día de negocio: 06:00 es la primera.

    Ordenar por este número deja la madrugada detrás de las 23:00, que es la
    cronología real del turno. También "pasada" y "futura" se deciden aquí: a
    la 01:00, las 09:00 de ese día pasaron hace dieciséis horas y las 02:00 aún
    no han llegado. Es el gemelo de ``businessDayOrder`` de la app.
    """
    return (hour - BUSINESS_DAY_CUTOFF_HOUR) % 24
