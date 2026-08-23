from datetime import date
from decimal import Decimal
from typing import Any

from restaurant_live_ops.workforce_source.projections import aggregate_projections, projections_path


def _intervalo(desde: str, medida: str, valor: float) -> dict[str, Any]:
    return {"from": desde, "to": desde, "measure": medida, "value": valor}


def test_utc_intervals_are_bucketed_by_madrid_hour() -> None:
    # 12:00Z en julio es la hora 14 en Madrid (UTC+2).
    filas = [_intervalo("2026-07-26T12:00:00.000Z", "VENTA", 100.0)]
    horas = aggregate_projections(filas, target_day=date(2026, 7, 26))
    assert [(h.hour, h.sales) for h in horas] == [(14, Decimal("100.0"))]


def test_winter_intervals_use_one_hour_offset() -> None:
    filas = [_intervalo("2026-01-26T12:00:00.000Z", "VENTA", 100.0)]
    horas = aggregate_projections(filas, target_day=date(2026, 1, 26))
    assert horas[0].hour == 13


def test_four_quarters_sum_into_one_hour() -> None:
    filas = [_intervalo(f"2026-07-26T12:{m:02d}:00.000Z", "VENTA", 25.0) for m in (0, 15, 30, 45)]
    horas = aggregate_projections(filas, target_day=date(2026, 7, 26))
    assert len(horas) == 1
    assert horas[0].sales == Decimal("100.0")


def test_the_night_after_midnight_belongs_to_the_business_day() -> None:
    # 23:00Z del 26 es la 01:00 del 27 en Madrid: madrugada del día de
    # NEGOCIO 26, la misma noche que la fuente de ventas pone al pie de la grid del 26.
    filas = [
        _intervalo("2026-07-26T23:00:00.000Z", "VENTA", 59.20),
        _intervalo("2026-07-26T12:00:00.000Z", "VENTA", 10.0),
    ]
    horas = aggregate_projections(filas, target_day=date(2026, 7, 26))
    assert [h.hour for h in horas] == [1, 14]


def test_the_early_morning_of_a_civil_day_is_not_its_business_day() -> None:
    # 22:00Z del 25 es la medianoche del 26 en Madrid: esa madrugada cierra el
    # día de negocio 25, no abre el 26.
    filas = [_intervalo("2026-07-25T22:00:00.000Z", "VENTA", 815.0)]
    assert aggregate_projections(filas, target_day=date(2026, 7, 26)) == []
    horas = aggregate_projections(filas, target_day=date(2026, 7, 25))
    assert [(h.hour, h.sales) for h in horas] == [(0, Decimal("815.0"))]


def test_the_business_day_ends_at_six_next_civil_morning() -> None:
    # 03:45Z del 27 = 05:45 Madrid: aún día 26. 04:00Z = 06:00: ya día 27.
    filas = [
        _intervalo("2026-07-27T03:45:00.000Z", "VENTA", 5.0),
        _intervalo("2026-07-27T04:00:00.000Z", "VENTA", 7.0),
    ]
    horas26 = aggregate_projections(filas, target_day=date(2026, 7, 26))
    horas27 = aggregate_projections(filas, target_day=date(2026, 7, 27))
    assert [(h.hour, h.sales) for h in horas26] == [(5, Decimal("5.0"))]
    assert [(h.hour, h.sales) for h in horas27] == [(6, Decimal("7.0"))]


def test_venta_and_gcs_land_in_the_same_hour() -> None:
    filas = [
        _intervalo("2026-07-26T12:00:00.000Z", "VENTA", 100.0),
        _intervalo("2026-07-26T12:00:00.000Z", "GCS", 12.0),
    ]
    horas = aggregate_projections(filas, target_day=date(2026, 7, 26))
    assert (horas[0].sales, horas[0].guest_counts) == (Decimal("100.0"), Decimal("12.0"))


def test_other_measures_are_ignored() -> None:
    filas = [
        _intervalo("2026-07-26T12:00:00.000Z", "IPT", 3.4),
        _intervalo("2026-07-26T12:00:00.000Z", "BPT", 1.2),
    ]
    assert aggregate_projections(filas, target_day=date(2026, 7, 26)) == []


def test_hour_with_only_gcs_still_appears() -> None:
    filas = [_intervalo("2026-07-26T12:00:00.000Z", "GCS", 12.0)]
    horas = aggregate_projections(filas, target_day=date(2026, 7, 26))
    assert (horas[0].hour, horas[0].sales, horas[0].guest_counts) == (
        14,
        Decimal(0),
        Decimal("12.0"),
    )


def test_hours_come_out_sorted() -> None:
    filas = [
        _intervalo("2026-07-26T16:00:00.000Z", "VENTA", 1.0),
        _intervalo("2026-07-26T08:00:00.000Z", "VENTA", 1.0),
    ]
    assert [h.hour for h in aggregate_projections(filas, target_day=date(2026, 7, 26))] == [10, 18]


def test_values_are_decimal_not_float() -> None:
    filas = [_intervalo("2026-07-26T12:00:00.000Z", "VENTA", 59.20)]
    horas = aggregate_projections(filas, target_day=date(2026, 7, 26))
    assert isinstance(horas[0].sales, Decimal)
    assert horas[0].sales == Decimal("59.2")


def test_path_uses_product_segment_for_the_restaurant_id() -> None:
    # En este endpoint "product" es el ID del restaurante, no un producto.
    assert projections_path("BIZ-TEST", "R001", date(2026, 7, 26)) == (
        "/importer/api/v1/business/BIZ-TEST/product/R001/projections/from/2026-07-26/to/2026-07-26"
    )
