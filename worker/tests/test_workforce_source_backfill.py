from __future__ import annotations

from datetime import date

from restaurant_live_ops.tz import days_between


def test_days_between_incluye_los_dos_extremos() -> None:
    assert days_between(date(2026, 3, 1), date(2026, 3, 3)) == [
        date(2026, 3, 1),
        date(2026, 3, 2),
        date(2026, 3, 3),
    ]


def test_days_between_cuenta_los_dias_del_cambio_de_hora() -> None:
    # Marzo tiene un día de 23 horas: contar por días, nunca por horas.
    dias = days_between(date(2026, 3, 28), date(2026, 3, 31))
    assert dias == [date(2026, 3, 28), date(2026, 3, 29), date(2026, 3, 30), date(2026, 3, 31)]


def test_days_between_con_un_solo_dia() -> None:
    assert days_between(date(2026, 3, 1), date(2026, 3, 1)) == [date(2026, 3, 1)]


def test_days_between_rango_invertido_no_devuelve_nada() -> None:
    assert days_between(date(2026, 3, 3), date(2026, 3, 1)) == []
