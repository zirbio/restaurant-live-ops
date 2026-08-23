import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from restaurant_live_ops.sales_source.parser import (
    TOTALS_TOLERANCE,
    MissingSalesTotalError,
    SalesSequenceError,
    parse_hourly_response,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sales" / "source_day.json"


@pytest.fixture
def payload() -> dict[str, Any]:
    fixture: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return cast(dict[str, Any], fixture["payload"])


def _with_sales_total(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared = [dict(row) for row in rows]
    totals_row = next((row for row in prepared if "_s0" in row), None)
    if totals_row is None:
        prepared.append({"_s0": "Total", "_s1": "0"})
    elif "_s1" not in totals_row:
        totals_row["_s1"] = "0"
    return prepared


def _parse(rows: list[dict[str, Any]], restaurant_id: str = "R001"):  # type: ignore[no-untyped-def]
    return parse_hourly_response(
        {
            "success": True,
            "metaData": {"fields": ["0", "12"]},
            "rows": _with_sales_total(rows),
        },
        restaurant_id=restaurant_id,
        sales_date=date(2026, 7, 26),
    )


def test_empty_cells_become_none_not_zero() -> None:
    dia = _parse([{"0": "9", "1": "", "3": "", "4": ""}], restaurant_id="R002")
    hora = dia.hours[0]
    assert hora.net is None
    assert hora.gc is None
    assert hora.drive_through_net is None


def test_unicode_thousands_separators_and_comma_decimal() -> None:
    # ExtJS separa millares con espacios Unicode variados (normal, duro, fino).
    # Los espacios raros de estos literales son exactamente lo que se prueba.
    dia = _parse([{"0": "14", "1": "1 234,56", "3": "1\xa0210"}])  # noqa: RUF001
    assert dia.hours[0].net == Decimal("1234.56")
    assert dia.hours[0].gc == 1210


def test_restaurant_without_drive_through_keeps_zero_and_missing_service_time() -> None:
    # Un cero numérico y una celda vacía son estados distintos y se conservan.
    dia = _parse([{"0": "14", "1": 1384.81, "4": 0, "9": ""}], restaurant_id="R002")
    hora = dia.hours[0]
    assert hora.drive_through_net == Decimal("0")
    assert hora.oepe is None


def test_money_is_decimal_never_float() -> None:
    dia = _parse([{"0": "14", "1": "0,10"}])
    assert isinstance(dia.hours[0].net, Decimal)


def test_json_numbers_are_parsed_without_float_drift() -> None:
    # Las celdas horarias llegan como número JSON, no como texto.
    dia = _parse([{"0": "14", "1": 2198.42}])
    assert dia.hours[0].net == Decimal("2198.42")


def test_unsuccessful_payload_raises() -> None:
    with pytest.raises(ValueError, match="no fue satisfactoria"):
        parse_hourly_response(
            {"success": False, "rows": []},
            restaurant_id="R001",
            sales_date=date(2026, 7, 26),
        )


def test_payload_without_sales_total_is_rejected(payload: dict[str, Any]) -> None:
    payload["rows"] = [row for row in payload["rows"] if "_s0" not in row]

    with pytest.raises(MissingSalesTotalError, match="missing-sales-total"):
        parse_hourly_response(
            payload,
            restaurant_id="R001",
            sales_date=date(2030, 1, 15),
        )


def test_counter_net_is_total_minus_drive_through_and_delivery() -> None:
    dia = _parse(
        [
            {
                "0": "14",
                "1": "100,00",
                "_s0": "Total",
                "_s1": "100,00",
                "_s4": "30,00",
                "_s10": "20,00",
            }
        ]
    )
    assert dia.totals.counter_net == Decimal("50.00")


def test_zero_sales_total_is_valid() -> None:
    dia = _parse([{"_s0": "Total", "_s1": "0"}])
    assert dia.totals.net == Decimal("0")


def test_totals_row_is_also_a_real_hour() -> None:
    # la fuente de ventas fusiona la fila de totales con la ÚLTIMA HORA: esa fila lleva a la
    # vez sus datos horarios ("0", "1"…) y los acumulados ("_s1"…). Descartarla
    # perdería la hora en curso, que es justo la que importa en esta app.
    dia = _parse(
        [
            {"0": "17", "1": "370,83"},
            {"0": "18", "1": "130,62", "_s0": "Total", "_s1": "501"},
        ]
    )
    assert [h.hour for h in dia.hours] == [17, 18]
    assert dia.hours[-1].net == Decimal("130.62")
    assert dia.totals.net == Decimal("501")


def test_rows_without_hour_are_not_parsed_as_hours() -> None:
    dia = _parse([{"0": "14", "1": "100,00"}, {"_s0": "Total", "_s1": "100,00"}])
    assert [h.hour for h in dia.hours] == [14]


def test_rounding_gap_under_one_euro_is_not_a_mismatch() -> None:
    # Una diferencia inferior a la tolerancia es redondeo, no un fallo.
    dia = _parse([{"0": "10", "1": "10,51", "_s0": "Total", "_s1": "11"}])
    assert dia.hourly_net_sum == Decimal("10.51")
    assert dia.totals_mismatch is None


def test_rounding_gap_over_one_euro_is_a_mismatch() -> None:
    dia = _parse([{"0": "10", "1": "10,00", "_s0": "Total", "_s1": "12"}])
    assert dia.totals_mismatch == Decimal("-2.00")
    assert TOTALS_TOLERANCE == Decimal("1.00")


def test_synthetic_payload_hours_sum_matches_totals_within_tolerance(
    payload: dict[str, Any],
) -> None:
    dia = parse_hourly_response(payload, restaurant_id="R001", sales_date=date(2030, 1, 15))
    assert len(dia.hours) == 2
    assert dia.totals_mismatch is None


def test_synthetic_payload_service_times_come_from_the_totals_row(
    payload: dict[str, Any],
) -> None:
    # Los tiempos diarios proceden de la fila de totales; no se reconstruyen
    # promediando las filas horarias.
    dia = parse_hourly_response(payload, restaurant_id="R001", sales_date=date(2030, 1, 15))
    assert (dia.totals.kvs, dia.totals.r2p, dia.totals.oepe) == (90, 100, 110)


def test_missing_daily_service_time_stays_none() -> None:
    # En la fila de totales el OEPE de R002 llega vacío: null, nunca 0.
    dia = _parse([{"0": "14", "1": "100,00", "_s0": "Total", "_s7": "70", "_s9": ""}], "R002")
    assert dia.totals.kvs == 70
    assert dia.totals.oepe is None


def test_synthetic_payload_channels_add_up_to_the_net_total(payload: dict[str, Any]) -> None:
    # Los canales sintéticos suman el neto total del fixture.
    dia = parse_hourly_response(payload, restaurant_id="R001", sales_date=date(2030, 1, 15))
    t = dia.totals
    assert t.net is not None
    canales = (
        (t.drive_through_net or Decimal(0))
        + (t.delivery_net or Decimal(0))
        + (t.counter_net or Decimal(0))
    )
    assert canales == t.net


def test_a_closed_source_day_crosses_midnight_once() -> None:
    # Una secuencia válida puede cruzar la medianoche una vez.
    dia = _parse(
        [
            {"0": 10, "1": "12.32"},
            {"0": 23, "1": "1233.92"},
            {"0": 0, "1": "536.61"},
            {"0": 2, "1": "23.83"},
        ],
        restaurant_id="R003",
    )
    ocurrencias = dia.sequenced_hours()
    assert [o.calendar_date for o in ocurrencias] == [
        date(2026, 7, 26),
        date(2026, 7, 26),
        date(2026, 7, 27),
        date(2026, 7, 27),
    ]
    assert {o.sales_date for o in ocurrencias} == {date(2026, 7, 26)}


def test_two_clock_wraps_recover_a_prior_day_carryover_prefix() -> None:
    # Una cola tardía de D-1 puede preceder al bloque principal de D. El día
    # de caja queda entre los dos cruces: D-1 → D → D+1.
    dia = _dia(
        [{"0": 22}, {"0": 0}, {"0": 10}, {"0": 23}, {"0": 0}],
        sales_date=date(2026, 8, 1),
    )

    ocurrencias = dia.sequenced_hours()
    assert [o.calendar_date for o in ocurrencias] == [
        date(2026, 7, 31),
        date(2026, 8, 1),
        date(2026, 8, 1),
        date(2026, 8, 1),
        date(2026, 8, 2),
    ]
    assert [o.sales_date for o in ocurrencias] == [
        date(2026, 7, 31),
        date(2026, 7, 31),
        date(2026, 8, 1),
        date(2026, 8, 1),
        date(2026, 8, 1),
    ]


def test_more_than_two_clock_wraps_is_rejected_as_ambiguous() -> None:
    dia = _dia([{"0": 22}, {"0": 0}, {"0": 10}, {"0": 0}, {"0": 10}, {"0": 0}])
    with pytest.raises(SalesSequenceError, match="más de dos medianoches"):
        dia.sequenced_hours()


def test_the_repeated_dst_hour_is_kept_twice() -> None:
    # El 25/10/2026 las 02:00 ocurren dos veces en Madrid. Ambas ventas son
    # reales y suman; deduplicarlas perdería una hora entera.
    dia = parse_hourly_response(
        {
            "success": True,
            "rows": _with_sales_total(
                [
                    {"0": 1, "1": "10.00"},
                    {"0": 2, "1": "20.00"},
                    {"0": 2, "1": "30.00"},
                    {"0": 3, "1": "40.00"},
                ]
            ),
        },
        restaurant_id="R003",
        sales_date=date(2026, 10, 25),
    )
    ocurrencias = dia.sequenced_hours()
    assert [o.fold for o in ocurrencias] == [0, 0, 1, 0]
    assert sum((o.row.net or Decimal(0) for o in ocurrencias), Decimal(0)) == Decimal("100.00")


def test_second_repeated_dst_hour_is_still_future_during_first_fold() -> None:
    # 02:30 CEST ocurre antes que la segunda 02:00 CET. Comparar dos datetime
    # con el mismo ZoneInfo por reloj de pared ignora ese orden absoluto y
    # aceptaría una venta que aún no ha sucedido.
    dia = parse_hourly_response(
        {
            "success": True,
            "rows": _with_sales_total(
                [
                    {"0": 2, "1": "40.00"},
                    {"0": 2, "1": "60.00"},
                ]
            ),
        },
        restaurant_id="R003",
        sales_date=date(2026, 10, 25),
    )
    primera_dos_y_media = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)

    assert dia.unelapsed_hours_with_sales(now=primera_dos_y_media) == [2]


def test_nonexistent_spring_dst_hour_is_rejected() -> None:
    # El 29/03/2026 Madrid salta de 01:59 a 03:00. Situar venta en 02:00
    # exigiría inventar un instante civil, así que la captura no se publica.
    dia = parse_hourly_response(
        {
            "success": True,
            "rows": _with_sales_total([{"0": 1}, {"0": 2, "1": "50.00"}, {"0": 3}]),
        },
        restaurant_id="R003",
        sales_date=date(2026, 3, 29),
    )

    with pytest.raises(SalesSequenceError, match="hora inexistente"):
        dia.sequenced_hours()


def test_empty_nonexistent_spring_hour_is_ignored() -> None:
    # Un feed puede conservar una hora técnica inexistente con importe y GC
    # cero. No representa un instante ni invalida el resto del día.
    dia = parse_hourly_response(
        {
            "success": True,
            "rows": _with_sales_total(
                [
                    {"0": 23, "1": "100.00"},
                    {"0": 0, "1": "50.00"},
                    {"0": 1, "1": "25.00"},
                    {"0": 2, "1": "0.00", "3": 0},
                    {"0": 3, "1": "10.00"},
                ]
            ),
        },
        restaurant_id="R001",
        sales_date=date(2026, 3, 28),
    )

    assert [occurrence.row.hour for occurrence in dia.sequenced_hours()] == [23, 0, 1, 3]


def test_a_repeated_normal_hour_is_rejected() -> None:
    dia = _dia([{"0": 12, "1": "10.00"}, {"0": 12, "1": "10.00"}])
    with pytest.raises(SalesSequenceError, match="hora repetida"):
        dia.sequenced_hours()


# --- Horas que todavía no han ocurrido -------------------------------------
#
# Una rejilla puede traer madrugada futura de otra fecha y aun cuadrar con su
# fila de totales. Por eso también hay que compararla con el reloj.

SABADO = date(2026, 8, 1)
TARDE_DEL_SABADO = datetime(2026, 8, 1, 15, 41, tzinfo=UTC)  # 17:41 de Madrid


def _dia(rows: list[dict[str, Any]], *, sales_date: date = SABADO):  # type: ignore[no-untyped-def]
    return parse_hourly_response(
        {
            "success": True,
            "metaData": {"fields": ["0", "12"]},
            "rows": _with_sales_total(rows),
        },
        restaurant_id="R003",
        sales_date=sales_date,
    )


def test_sales_in_an_hour_that_has_not_happened_yet_are_flagged() -> None:
    dia = _dia([{"0": "14", "1": "1018,38"}, {"0": "0", "1": "1168,02"}])
    assert dia.unelapsed_hours_with_sales(now=TARDE_DEL_SABADO) == [0]


def test_the_current_hour_is_not_flagged_because_it_is_still_selling() -> None:
    # A las 17:41 la hora 17 va a medias: su venta es legítima.
    dia = _dia([{"0": "17", "1": "229,32"}])
    assert dia.unelapsed_hours_with_sales(now=TARDE_DEL_SABADO) == []


def test_an_unelapsed_hour_without_sales_is_not_flagged() -> None:
    # la fuente de ventas emite la hora futura vacía o a cero; eso no es contaminación.
    dia = _dia([{"0": "0", "1": ""}, {"0": "1", "1": 0}])
    assert dia.unelapsed_hours_with_sales(now=TARDE_DEL_SABADO) == []


def test_a_closed_day_has_no_unelapsed_hours() -> None:
    # En un día ya cerrado toda su madrugada ocurrió: nada que marcar.
    dia = _dia([{"0": "3", "1": "210,22"}], sales_date=date(2026, 7, 25))
    assert dia.unelapsed_hours_with_sales(now=TARDE_DEL_SABADO) == []


def test_at_half_past_three_in_the_morning_the_early_hours_already_happened() -> None:
    # 03:30 de Madrid del 2 de agosto. El 23→0 demuestra que las filas 0 y 5
    # pertenecen al día civil 2: la 0 ya pasó y la 5 aún no.
    madrugada = datetime(2026, 8, 2, 1, 30, tzinfo=UTC)
    dia = _dia([{"0": "23"}, {"0": "0", "1": "1168,02"}, {"0": "5", "1": "18,47"}])
    assert dia.unelapsed_hours_with_sales(now=madrugada) == [5]


@pytest.mark.parametrize(
    ("columna", "valor"),
    [
        ("1", "12,40"),  # venta neta
        ("2", "15,00"),  # venta bruta
        ("3", "47"),  # guest counts
        ("4", "88,10"),  # drive-through neto
        ("5", "97,00"),  # drive-through bruto
        ("6", "9"),  # drive-through coches
        ("10", "88,10"),  # Delivery neto
        ("11", "97,00"),  # Delivery bruto
        ("12", "6"),  # Delivery pedidos
    ],
)
def test_any_single_measure_makes_an_unelapsed_hour_suspicious(columna: str, valor: str) -> None:
    # Una hora fantasma no tiene por qué traer el dinero: puede llegar con el
    # neto vacío y sólo clientes, o sólo pedidos de Delivery. Cada medida se
    # prueba SOLA a propósito — una fila con varias pasaría aunque el código
    # mirase únicamente una de ellas.
    # El salto 23→2 sitúa la fila en el día civil siguiente. Una fila 2 que
    # aparezca al PRINCIPIO sería la madrugada ya ocurrida del mismo día.
    dia = _dia([{"0": "23"}, {"0": "2", columna: valor}])
    assert dia.unelapsed_hours_with_sales(now=TARDE_DEL_SABADO) == [2]


def test_a_numeric_zero_drive_through_is_not_activity() -> None:
    # Los ceros de un canal no prueban actividad en una hora futura.
    dia = _dia([{"0": "0", "1": "", "3": "", "4": 0, "5": 0, "6": 0, "9": ""}])
    assert dia.unelapsed_hours_with_sales(now=TARDE_DEL_SABADO) == []


def test_service_times_alone_are_not_activity() -> None:
    # KVS, R2P y OEPE describen CÓMO se despachó, no que se despachara, y por
    # eso quedan fuera de has_activity. La lista de medidas se ve incompleta e
    # invita a "completarla": esto fija que no se haga. El error saldría caro —
    # una hora futura con sólo tiempos tumbaría el día entero del restaurante.
    dia = _dia([{"0": "2", "7": 120, "8": 130, "9": 150}])
    assert dia.unelapsed_hours_with_sales(now=TARDE_DEL_SABADO) == []


def test_the_hour_about_to_start_is_not_flagged() -> None:
    # A las 13:59:58 la hora 14 está a dos segundos. El reloj de la fuente de ventas no es el
    # del worker, y una comparación sin margen convierte ese desfase en un
    # rechazo falso: un local sin refrescar y una alarma roja que no toca.
    en_punto = datetime(2026, 8, 1, 11, 59, 58, tzinfo=UTC)  # 13:59:58 de Madrid
    dia = _dia([{"0": "13", "1": "500,00"}, {"0": "14", "1": "12,40"}])
    assert dia.unelapsed_hours_with_sales(now=en_punto) == []


def test_the_grace_margin_is_exactly_five_minutes_wide() -> None:
    # Fija el ancho del margen por los dos lados. Sin esto se podría doblar o
    # cuadruplicar sin que ningún test protestara, y un margen de veinte
    # minutos dejaría un tercio de cada hora sin vigilar.
    dia = _dia([{"0": "14", "1": "12,40"}])
    assert dia.unelapsed_hours_with_sales(now=datetime(2026, 8, 1, 11, 54, tzinfo=UTC)) == [14]
    assert dia.unelapsed_hours_with_sales(now=datetime(2026, 8, 1, 11, 55, tzinfo=UTC)) == []


def test_an_hour_still_far_away_is_flagged() -> None:
    # El margen es de minutos, no de horas: a las 13:30 la hora 14 sigue sin
    # haber llegado y su venta no puede existir.
    lejos = datetime(2026, 8, 1, 11, 30, tzinfo=UTC)  # 13:30 de Madrid
    dia = _dia([{"0": "13", "1": "500,00"}, {"0": "14", "1": "12,40"}])
    assert dia.unelapsed_hours_with_sales(now=lejos) == [14]


def test_at_five_to_six_the_whole_business_day_has_already_happened() -> None:
    # 05:58 de Madrid del 2 de agosto: el día de negocio vivo sigue siendo el 1
    # y le quedan dos minutos. TODAS sus horas han ocurrido. El margen no puede
    # hacer que el día siguiente empiece antes de tiempo y marque el día entero.
    antes_del_corte = datetime(2026, 8, 2, 3, 58, tzinfo=UTC)  # 05:58 de Madrid
    dia = _dia([{"0": "14", "1": "1018,38"}, {"0": "5", "1": "18,47"}])
    assert dia.unelapsed_hours_with_sales(now=antes_del_corte) == []


def test_a_repeated_hour_is_listed_once() -> None:
    # Un cierre dentro de la hora 2 puede dejar una parte al principio del día
    # la fuente de ventas y otra tras cruzar medianoche. Son dos fechas civiles distintas; si
    # solo la segunda es futura, el aviso sigue nombrando la hora una vez.
    dia = _dia(
        [
            {"0": "2", "1": "50,00"},
            {"0": "23"},
            {"0": "2", "1": "60,00"},
        ]
    )
    assert dia.unelapsed_hours_with_sales(now=TARDE_DEL_SABADO) == [2]


def test_unelapsed_hours_come_back_in_business_day_order() -> None:
    # A las 22:10 del día vivo, las 23:00 van antes que las 00:00: se listan
    # como se viven, no por su número.
    noche = datetime(2026, 8, 1, 20, 10, tzinfo=UTC)  # 22:10 de Madrid
    dia = _dia([{"0": "23", "1": "1199,41"}, {"0": "0", "1": "1168,02"}])
    assert dia.unelapsed_hours_with_sales(now=noche) == [23, 0]


def test_a_refund_in_an_hour_that_has_not_happened_is_also_flagged() -> None:
    # Una devolución tampoco puede ocurrir en una hora que no ha llegado.
    dia = _dia([{"0": "23"}, {"0": "2", "1": "-21,21"}])
    assert dia.unelapsed_hours_with_sales(now=TARDE_DEL_SABADO) == [2]
