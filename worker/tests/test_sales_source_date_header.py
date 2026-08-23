from datetime import date, timedelta

import pytest

from restaurant_live_ops.sales_source.date_header import (
    MAX_VERIFIABLE_DAYS,
    UnverifiableDateError,
    assert_verifiable,
    matches_date,
    parse_date_label,
)


def test_parses_plain_label() -> None:
    assert parse_date_label("Thu 25 Jun") == (25, 6)


def test_leading_day_count_does_not_win() -> None:
    # "2 days ago - Wed 24 Jun": el 2 inicial no puede ganarle al 24.
    assert parse_date_label("2 days ago - Wed 24 Jun") == (24, 6)


def test_parses_yesterday_prefix() -> None:
    assert parse_date_label("Yesterday - Fri 26 Jun") == (26, 6)


def test_returns_none_when_no_date_present() -> None:
    assert parse_date_label("Sales view") is None


def test_matches_date_true_only_on_exact_match() -> None:
    assert matches_date("Sun 26 Jul", date(2026, 7, 26)) is True
    assert matches_date("Sat 25 Jul", date(2026, 7, 26)) is False
    assert matches_date("Sun 26 Jun", date(2026, 7, 26)) is False


def test_unreadable_label_never_matches() -> None:
    # Sin fecha legible no se acepta la captura: en la duda, se descarta.
    assert matches_date("", date(2026, 7, 26)) is False


def test_yesterday_label_is_rejected_even_though_it_parses() -> None:
    # Si la fuente muestra ayer, parsea bien,
    # pero no es hoy, así que la captura no se acepta.
    assert parse_date_label("Yesterday - Sat 25 Jul") == (25, 7)
    assert matches_date("Yesterday - Sat 25 Jul", date(2026, 7, 26)) is False


def test_matches_date_acepta_el_dia_pedido() -> None:
    # La recuperación de huecos pide un día concreto, no hoy.
    assert matches_date("Fri 20 Mar", date(2026, 3, 20))


def test_matches_date_rechaza_cualquier_otro_dia() -> None:
    # El día pedido es el 20; la fuente enseña el 19. Aceptarlo estamparía la
    # venta del 19 como si fuera del 20.
    assert not matches_date("Thu 19 Mar", date(2026, 3, 20))


def test_matches_date_rechaza_el_mismo_dia_de_otro_mes() -> None:
    assert not matches_date("Fri 20 Mar", date(2026, 4, 20))


def test_assert_verifiable_acepta_un_dia_reciente() -> None:
    assert_verifiable(date(2026, 7, 20), date(2026, 7, 27))
    assert_verifiable(date(2026, 7, 27), date(2026, 7, 27))


def test_assert_verifiable_rechaza_el_mismo_dia_del_ano_pasado() -> None:
    # El caso peligroso: el encabezado no lleva año, así que "Today - Mon 27
    # Jul" coincidiría en día y mes con el 27 de julio del año pasado y se
    # guardaría la venta de HOY con la fecha de entonces.
    with pytest.raises(UnverifiableDateError):
        assert_verifiable(date(2025, 7, 27), date(2026, 7, 27))


def test_assert_verifiable_rechaza_el_futuro() -> None:
    with pytest.raises(UnverifiableDateError):
        assert_verifiable(date(2026, 7, 28), date(2026, 7, 27))


def test_assert_verifiable_acepta_justo_en_el_borde() -> None:
    hoy = date(2026, 7, 27)
    assert_verifiable(hoy - timedelta(days=MAX_VERIFIABLE_DAYS), hoy)
    with pytest.raises(UnverifiableDateError):
        assert_verifiable(hoy - timedelta(days=MAX_VERIFIABLE_DAYS + 1), hoy)
