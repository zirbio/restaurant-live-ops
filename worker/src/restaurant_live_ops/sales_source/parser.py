"""Parser de la rejilla horaria de la fuente de ventas.

Una fila por hora con claves numéricas ``"0".."12"``. Mapeo de columnas:

    0  hora (0-23)            7  KVS   (s)
    1  venta neta (EUR)       8  R2P   (s)
    2  venta bruta (EUR)      9  OEPE  (s)
    3  guest count           10  Delivery neto (EUR)
    4  drive-through neto (EUR)     11  Delivery bruto (EUR)
    5  drive-through bruto (EUR)    12  nº pedidos Delivery
    6  drive-through coches

Los acumulados del día llegan en claves ``"_s1".."_s12"`` de la **misma fila
que la última hora**, no en una fila aparte: esa fila cuenta como hora y como
totales a la vez.

Las celdas vacías llegan como ``""`` y se convierten en ``None``, nunca en 0:
un cero falso contamina cualquier resta o media. El dinero se parsea a
``Decimal`` para evitar la deriva de la coma flotante.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from restaurant_live_ops.tz import BUSINESS_DAY_CUTOFF_HOUR, MADRID, to_madrid

# La fila de totales que devuelve la fuente de ventas viene redondeada a euros enteros, así
# que nunca cuadra al céntimo con la suma horaria. Por debajo de este margen
# es redondeo; por encima, un fallo de parseo que debe hacer fallar el ciclo.
TOTALS_TOLERANCE = Decimal("1.00")

# Margen conservador al decidir si una hora ya ocurrió. Evita rechazar una
# captura por un pequeño desfase entre sistemas sin tolerar horas futuras. Es
# distinto de la cortesía para datos de personal que llegan tarde.
CLOCK_SKEW_GRACE_MINUTES = 5

# Cualquier racha de espacio Unicode (normal, duro, fino…) es un separador de
# millares de ExtJS y hay que eliminarla antes de parsear.
_WS = re.compile(r"\s")


class SalesSequenceError(ValueError):
    """La secuencia horaria no permite recuperar una fecha civil sin adivinar."""


class MissingSalesTotalError(ValueError):
    """La fuente no entregó el total neto que permite validar el día."""


class SalesTotalsMismatchError(ValueError):
    """Las horas no cuadran con el total neto declarado por la fuente."""


class FutureSalesError(ValueError):
    """El día contiene actividad de horas civiles que todavía no han ocurrido."""


@dataclass(frozen=True)
class SalesHour:
    hour: int
    net: Decimal | None
    gross: Decimal | None
    gc: int | None
    drive_through_net: Decimal | None
    drive_through_gross: Decimal | None
    drive_through_cars: int | None
    kvs: int | None
    r2p: int | None
    oepe: int | None
    delivery_net: Decimal | None
    delivery_gross: Decimal | None
    delivery_count: int | None

    @property
    def has_activity(self) -> bool:
        """¿Esta hora registra algo? Cualquier importe o recuento no nulo.

        No basta con mirar la venta neta: una hora puede llegar con el importe
        vacío y traer clientes o pedidos de Delivery, y esos contaminan el
        ticket medio y el reparto por canales igual que contaminaría el dinero.
        Los tiempos de servicio quedan fuera a propósito: describen cómo se
        despachó, no que se despachara.

        Un 0 numérico NO es actividad.
        """
        medidas = (
            self.net,
            self.gross,
            self.gc,
            self.drive_through_net,
            self.drive_through_gross,
            self.drive_through_cars,
            self.delivery_net,
            self.delivery_gross,
            self.delivery_count,
        )
        return any(v is not None and v != 0 for v in medidas)


@dataclass(frozen=True)
class SalesHourOccurrence:
    """Una fila la fuente de ventas situada en el calendario y en el día operativo común.

    la fuente de ventas conserva el orden del día de caja, pero no entrega ``calendar_date``.
    Se recupera con sus descensos de hora, incluida una posible cola de D-1
    antes del bloque principal de D. ``sales_date`` es la fecha canónica de la
    app (06:00→06:00), que puede diferir de la fecha del encabezado.
    """

    row_index: int
    row: SalesHour
    calendar_date: date
    sales_date: date
    fold: int = 0

    @property
    def started_at(self) -> datetime:
        """Comienzo real de la hora en Europe/Madrid, incluido el fold de octubre."""
        return datetime(
            self.calendar_date.year,
            self.calendar_date.month,
            self.calendar_date.day,
            self.row.hour,
            tzinfo=MADRID,
            fold=self.fold,
        )


@dataclass(frozen=True)
class SalesDayTotals:
    net: Decimal | None
    gross: Decimal | None
    gc: int | None
    drive_through_net: Decimal | None
    drive_through_gross: Decimal | None
    drive_through_cars: int | None
    kvs: int | None
    r2p: int | None
    oepe: int | None
    delivery_net: Decimal | None
    delivery_gross: Decimal | None
    delivery_count: int | None

    @property
    def counter_net(self) -> Decimal | None:
        """Mostrador + kiosko = neto total - drive-through - Delivery."""
        if self.net is None:
            return None
        return self.net - (self.drive_through_net or Decimal(0)) - (self.delivery_net or Decimal(0))


@dataclass(frozen=True)
class SalesDay:
    restaurant_id: str
    # Fecha de caja que muestra la fuente de ventas. La fecha operativa 06→06 se deriva por
    # fila en `sequenced_hours`; no son el mismo concepto.
    sales_date: date
    hours: list[SalesHour]
    totals: SalesDayTotals

    @property
    def hourly_net_sum(self) -> Decimal:
        """Suma de la venta neta horaria: la cifra buena, al céntimo."""
        return sum((h.net for h in self.hours if h.net is not None), Decimal(0))

    @property
    def totals_mismatch(self) -> Decimal | None:
        """Descuadre real frente a la fila de totales, o ``None`` si es redondeo."""
        if self.totals.net is None:
            return None
        diff = self.hourly_net_sum - self.totals.net
        return None if abs(diff) <= TOTALS_TOLERANCE else diff

    def sequenced_hours(self) -> list[SalesHourOccurrence]:
        """Recupera la fecha civil de cada fila a partir del orden de la fuente de ventas.

        Un descenso de hora avanza al día civil siguiente. Normalmente la
        secuencia cubre ``sales_date`` y su madrugada final. la fuente de ventas puede anteponer
        una cola tardía del día de caja anterior; entonces hay dos descensos y
        la secuencia completa cubre ``D-1 → D → D+1``. Más de dos no tiene una
        correspondencia demostrable y se rechaza.

        Una hora idéntica solo es válida en el cambio de horario de octubre,
        cuando las 02:00 ocurren dos veces. Fuera de ahí duplicaría venta.
        """
        total_wraps = 0
        previous_hour: int | None = None
        for row in self.hours:
            if not 0 <= row.hour <= 23:
                raise SalesSequenceError(
                    f"la fuente de ventas devolvió una hora fuera de rango: {row.hour}"
                )
            if previous_hour is not None and row.hour < previous_hour:
                total_wraps += 1
            previous_hour = row.hour
        if total_wraps > 2:
            raise SalesSequenceError(
                "la fuente de ventas devolvió una secuencia con más de dos medianoches"
            )

        # Con dos vueltas, el día de caja que muestra el encabezado es el día
        # central: la primera vuelta cierra la cola tardía de D-1 y la segunda
        # cierra el bloque principal de D. Con cero o una, la primera fila es D.
        calendar_day = self.sales_date - timedelta(days=1) if total_wraps == 2 else self.sales_date
        previous_hour = None
        seen: dict[tuple[date, int], int] = {}
        occurrences: list[SalesHourOccurrence] = []

        for row_index, row in enumerate(self.hours):
            if previous_hour is not None and row.hour < previous_hour:
                calendar_day += timedelta(days=1)

            if not _local_hour_exists(calendar_day, row.hour):
                if not row.has_activity:
                    # Algunos feeds conservan el cubo técnico 02:00 del salto
                    # de marzo con ceros. No representa un instante: se audita
                    # en crudo, pero no se publica en la rejilla civil.
                    previous_hour = row.hour
                    continue
                raise SalesSequenceError(
                    f"la fuente de ventas devolvió la hora inexistente {row.hour:02d}:00 el "
                    f"{calendar_day.isoformat()} por el cambio de horario"
                )

            key = (calendar_day, row.hour)
            repeated = seen.get(key, 0)
            if repeated:
                if repeated > 1 or not _is_repeated_dst_hour(calendar_day, row.hour):
                    raise SalesSequenceError(
                        "la fuente de ventas devolvió la hora repetida "
                        f"{row.hour:02d}:00 fuera del cambio "
                        "de horario"
                    )
                fold = 1
            else:
                fold = 0
            seen[key] = repeated + 1

            operating_day = (
                calendar_day
                if row.hour >= BUSINESS_DAY_CUTOFF_HOUR
                else calendar_day - timedelta(days=1)
            )
            occurrences.append(
                SalesHourOccurrence(
                    row_index=row_index,
                    row=row,
                    calendar_date=calendar_day,
                    sales_date=operating_day,
                    fold=fold,
                )
            )
            previous_hour = row.hour

        return occurrences

    def unelapsed_hours_with_sales(self, *, now: datetime) -> list[int]:
        """Horas con actividad que todavía no han ocurrido.

        Una rejilla coherente consigo misma aún puede contener horas futuras;
        por eso se contrasta también con el reloj. Un día cerrado no tiene
        horas futuras y pasa de largo.
        """
        # La tolerancia mueve el instante, no el día de negocio. Una hora tras
        # el salto de medianoche pertenece al día civil siguiente.
        # La comparación se hace en UTC. En el atraso de octubre hay dos 02:00
        # con el mismo ZoneInfo; Python las compara por reloj de pared si se
        # dejan en Madrid y puede considerar ocurrida la segunda durante la
        # primera. UTC conserva el orden real de ambos instantes.
        limite = to_madrid(now).astimezone(UTC) + timedelta(minutes=CLOCK_SKEW_GRACE_MINUTES)
        futuras: list[int] = []
        for occurrence in self.sequenced_hours():
            if not occurrence.row.has_activity or occurrence.started_at.astimezone(UTC) <= limite:
                continue
            if occurrence.row.hour not in futuras:
                futuras.append(occurrence.row.hour)
        return futuras


def validate_publishable_day(day: SalesDay, *, now: datetime | None) -> None:
    """Rechaza cualquier día que no pueda publicarse sin inventar o contaminar datos."""
    if day.totals.net is None:
        raise MissingSalesTotalError("missing-sales-total")
    if day.totals_mismatch is not None:
        raise SalesTotalsMismatchError("sales-total-mismatch")
    day.sequenced_hours()
    if now is not None and day.unelapsed_hours_with_sales(now=now):
        raise FutureSalesError("future-sales-hours")


def _is_repeated_dst_hour(calendar_day: date, hour: int) -> bool:
    """True solo para la hora que se repite al atrasar el reloj de Madrid."""
    first = datetime(
        calendar_day.year, calendar_day.month, calendar_day.day, hour, tzinfo=MADRID, fold=0
    )
    second = datetime(
        calendar_day.year, calendar_day.month, calendar_day.day, hour, tzinfo=MADRID, fold=1
    )
    first_utc = first.astimezone(UTC)
    second_utc = second.astimezone(UTC)
    # En octubre fold=1 ocurre una hora DESPUÉS. En marzo la hora inexistente
    # produce el orden contrario y no se debe aceptar como una repetición real.
    return first.utcoffset() != second.utcoffset() and first_utc < second_utc


def _local_hour_exists(calendar_day: date, hour: int) -> bool:
    """Comprueba que la hora de pared representa algún instante real en Madrid."""
    for fold in (0, 1):
        candidate = datetime(
            calendar_day.year,
            calendar_day.month,
            calendar_day.day,
            hour,
            tzinfo=MADRID,
            fold=fold,
        )
        roundtrip = candidate.astimezone(UTC).astimezone(MADRID)
        if (roundtrip.date(), roundtrip.hour) == (calendar_day, hour):
            return True
    return False


def _clean(s: str) -> str:
    return _WS.sub("", s).replace(",", ".").strip()


def _to_decimal(v: Any) -> Decimal | None:
    if v is None or v == "" or isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return Decimal(str(v))
    s = _clean(str(v))
    return Decimal(s) if s else None


def _to_int(v: Any) -> int | None:
    if v is None or v == "" or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return round(v)
    s = _clean(str(v))
    return round(float(s)) if s else None


def _parse_hour(row: dict[str, Any]) -> SalesHour:
    return SalesHour(
        hour=int(row["0"]),
        net=_to_decimal(row.get("1")),
        gross=_to_decimal(row.get("2")),
        gc=_to_int(row.get("3")),
        drive_through_net=_to_decimal(row.get("4")),
        drive_through_gross=_to_decimal(row.get("5")),
        drive_through_cars=_to_int(row.get("6")),
        kvs=_to_int(row.get("7")),
        r2p=_to_int(row.get("8")),
        oepe=_to_int(row.get("9")),
        delivery_net=_to_decimal(row.get("10")),
        delivery_gross=_to_decimal(row.get("11")),
        delivery_count=_to_int(row.get("12")),
    )


def _parse_totals(row: dict[str, Any] | None) -> SalesDayTotals:
    row = row or {}
    return SalesDayTotals(
        net=_to_decimal(row.get("_s1")),
        gross=_to_decimal(row.get("_s2")),
        gc=_to_int(row.get("_s3")),
        drive_through_net=_to_decimal(row.get("_s4")),
        drive_through_gross=_to_decimal(row.get("_s5")),
        drive_through_cars=_to_int(row.get("_s6")),
        kvs=_to_int(row.get("_s7")),
        r2p=_to_int(row.get("_s8")),
        oepe=_to_int(row.get("_s9")),
        delivery_net=_to_decimal(row.get("_s10")),
        delivery_gross=_to_decimal(row.get("_s11")),
        delivery_count=_to_int(row.get("_s12")),
    )


def parse_hourly_response(
    payload: dict[str, Any],
    *,
    restaurant_id: str,
    sales_date: date,
) -> SalesDay:
    """Convierte la respuesta del store horario en métricas tipadas."""
    if not payload.get("success"):
        raise ValueError("la respuesta horaria de la fuente de ventas no fue satisfactoria")

    rows: list[dict[str, Any]] = payload.get("rows") or []
    # La fila de totales también trae su hora, así que se parsea como hora.
    hours = [_parse_hour(r) for r in rows if "0" in r]
    totals_row = next((r for r in rows if "_s0" in r), None)

    day = SalesDay(
        restaurant_id=restaurant_id,
        sales_date=sales_date,
        hours=hours,
        totals=_parse_totals(totals_row),
    )
    if day.totals.net is None:
        raise MissingSalesTotalError("missing-sales-total")
    return day
