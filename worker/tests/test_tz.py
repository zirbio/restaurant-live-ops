from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from restaurant_live_ops.tz import business_date, to_madrid, today_madrid

MADRID = ZoneInfo("Europe/Madrid")


def test_today_madrid_uses_madrid_not_utc() -> None:
    # 23:30 UTC del 25 de julio ya es el día 26 en Madrid (verano, UTC+2).
    momento = datetime(2026, 7, 25, 23, 30, tzinfo=UTC)
    assert today_madrid(now=momento) == date(2026, 7, 26)


def test_to_madrid_summer_offset() -> None:
    # El intervalo de la fuente de personal que empieza a las 12:00Z es la hora 14 en Madrid.
    assert to_madrid(datetime(2026, 7, 26, 12, 0, tzinfo=UTC)).hour == 14


def test_to_madrid_winter_offset() -> None:
    # En enero el desfase es de una hora: 12:00Z es la hora 13 en Madrid.
    assert to_madrid(datetime(2026, 1, 26, 12, 0, tzinfo=UTC)).hour == 13


def test_business_cutoff_uses_the_winter_madrid_offset() -> None:
    before = datetime.fromisoformat("2026-01-15T05:59:00+01:00")
    at_cutoff = datetime.fromisoformat("2026-01-15T06:00:00+01:00")

    assert business_date(before) == date(2026, 1, 14)
    assert business_date(at_cutoff) == date(2026, 1, 15)


def test_to_madrid_skips_the_nonexistent_spring_hour() -> None:
    before_change = to_madrid(datetime.fromisoformat("2026-03-29T00:30:00+00:00"))
    after_change = to_madrid(datetime.fromisoformat("2026-03-29T01:30:00+00:00"))

    assert before_change.isoformat() == "2026-03-29T01:30:00+01:00"
    assert after_change.isoformat() == "2026-03-29T03:30:00+02:00"


def test_to_madrid_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="sin zona horaria"):
        to_madrid(datetime(2026, 7, 26, 12, 0))  # noqa: DTZ001


def test_business_date_before_cutoff_belongs_to_previous_day() -> None:
    # Un turno de R003 a las 03:00 del día 26 es el día de negocio 25.
    madrugada = datetime(2026, 7, 26, 3, 0, tzinfo=MADRID)
    assert business_date(madrugada) == date(2026, 7, 25)


def test_business_date_just_before_cutoff_belongs_to_previous_day() -> None:
    # El minuto anterior al corte es el último del día de negocio que se cierra.
    assert business_date(datetime(2026, 7, 26, 5, 59, tzinfo=MADRID)) == date(2026, 7, 25)


def test_business_date_at_cutoff_belongs_to_same_day() -> None:
    # El corte operativo configurado comienza a las 06:00 de Madrid.
    assert business_date(datetime(2026, 7, 26, 6, 0, tzinfo=MADRID)) == date(2026, 7, 26)
