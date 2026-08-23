"""Reparto de la presencia de personal por horas del día de NEGOCIO.

La rejilla del día D va de las 06:00 de D a las 06:00 de D+1, igual que la
grid de ventas de la fuente de ventas: así la columna F/A de una fila acompaña a la venta de
esa misma noche, no a la de la noche anterior.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

from restaurant_live_ops.tz import MADRID
from restaurant_live_ops.workforce_source.hourly import (
    HourlyStaffing,
    Interval,
    hourly_staffing,
    hours_settled_by,
    merge_intervals,
)


def md(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=MADRID)


DIA = date(2026, 7, 26)
# Posterior a TODOS los días que se prueban aquí, incluidos los dos cambios de
# hora: así ningún caso queda truncado por accidente y se prueba lo que se cree.
CERRADO = md(2026, 12, 31, 12)


def by_hour(
    clocked: list[Interval],
    assigned: list[Interval],
    *,
    day: date,
    now: datetime,
    crew: Callable[[str], bool] | None = None,
) -> dict[int, HourlyStaffing]:
    return {f.hour: f for f in hourly_staffing(clocked, assigned, day=day, now=now, crew=crew)}


def test_one_person_counts_in_every_hour_they_touch() -> None:
    fichajes = [Interval("a", md(2026, 7, 26, 9, 30), md(2026, 7, 26, 11, 15))]
    filas = by_hour(fichajes, [], day=DIA, now=CERRADO)
    assert filas[9].clocked_count == 1
    assert filas[10].clocked_count == 1
    assert filas[11].clocked_count == 1
    assert filas[9].clocked_minutes == 30
    assert filas[10].clocked_minutes == 60
    assert filas[11].clocked_minutes == 15


def test_switching_task_within_the_hour_does_not_count_twice() -> None:
    # Cambiar de tarea dentro de la hora no duplica a la persona.
    fichajes = [
        Interval("a", md(2026, 7, 26, 13, 0), md(2026, 7, 26, 13, 30)),
        Interval("a", md(2026, 7, 26, 13, 30), md(2026, 7, 26, 14, 0)),
    ]
    filas = by_hour(fichajes, [], day=DIA, now=CERRADO)
    assert filas[13].clocked_count == 1
    assert filas[13].clocked_minutes == 60


def test_overlapping_intervals_for_one_person_are_merged() -> None:
    fichajes = [
        Interval("EMP-TEST-001", md(2026, 7, 26, 8, 0), md(2026, 7, 26, 9, 0)),
        Interval("EMP-TEST-001", md(2026, 7, 26, 8, 30), md(2026, 7, 26, 9, 30)),
    ]

    filas = by_hour(fichajes, [], day=DIA, now=CERRADO)

    assert filas[8].clocked_count == 1
    assert filas[8].clocked_minutes == 60
    assert filas[9].clocked_minutes == 30
    assert all(
        row.clocked_minutes is None or row.clocked_minutes <= (row.clocked_count or 0) * 60
        for row in filas.values()
    )


def test_overlapping_assignments_for_one_person_obey_the_minutes_invariant() -> None:
    asignados = [
        Interval("EMP-TEST-001", md(2026, 7, 26, 8, 0), md(2026, 7, 26, 9, 0)),
        Interval("EMP-TEST-001", md(2026, 7, 26, 8, 30), md(2026, 7, 26, 9, 30)),
    ]

    filas = by_hour([], asignados, day=DIA, now=CERRADO)

    assert filas[8].assigned_count == 1
    assert filas[8].assigned_minutes == 60
    assert filas[9].assigned_minutes == 30
    assert all(row.assigned_minutes <= row.assigned_count * 60 for row in filas.values())


def test_merge_intervals_distinguishes_both_repeated_hour_folds() -> None:
    fichajes = [
        Interval(
            "EMP-TEST-001",
            datetime(2026, 10, 25, 2, 0, tzinfo=MADRID, fold=fold),
            datetime(2026, 10, 25, 2, 30, tzinfo=MADRID, fold=fold),
        )
        for fold in (0, 1)
    ]

    fusionados = merge_intervals(fichajes)

    assert len(fusionados) == 2
    assert (
        sum(
            (tramo.end.astimezone(UTC) - tramo.start.astimezone(UTC)).total_seconds()
            for tramo in fusionados
            if tramo.end is not None
        )
        / 60
        == 60
    )


def test_repeated_hour_counts_both_folds_in_clocked_and_assigned_minutes() -> None:
    dia = date(2026, 10, 24)
    tramos = [
        Interval(
            "EMP-TEST-001",
            datetime(2026, 10, 25, 2, 0, tzinfo=MADRID, fold=fold),
            datetime(2026, 10, 25, 2, 30, tzinfo=MADRID, fold=fold),
        )
        for fold in (0, 1)
    ]

    fila = by_hour(tramos, tramos, day=dia, now=CERRADO)[2]

    assert fila.clocked_count == 1
    assert fila.assigned_count == 1
    assert fila.clocked_minutes == 60
    assert fila.assigned_minutes == 60
    assert fila.clocked_minutes <= fila.clocked_count * 120
    assert fila.assigned_minutes <= fila.assigned_count * 120


def test_a_future_checkout_is_clipped_to_now() -> None:
    # Fichaje cuadrado por adelantado: entra a las 10:00 y "sale" a las 18:00,
    # pero son las 16:30. Las horas 17 y 18 no han ocurrido.
    ahora = md(2026, 7, 26, 16, 30)
    fichajes = [Interval("a", md(2026, 7, 26, 10, 0), md(2026, 7, 26, 18, 0))]
    filas = by_hour(fichajes, [], day=DIA, now=ahora)
    assert filas[16].clocked_count == 1
    assert filas[16].clocked_minutes == 30
    assert 17 not in filas
    assert 18 not in filas


def test_an_open_punch_counts_up_to_now() -> None:
    ahora = md(2026, 7, 26, 15, 20)
    fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
    filas = by_hour(fichajes, [], day=DIA, now=ahora)
    assert filas[14].clocked_minutes == 60
    assert filas[15].clocked_minutes == 20


def test_a_future_hour_reports_null_clocked_not_zero() -> None:
    # Un cero diría "no fichó nadie"; la verdad es "todavía no ha pasado".
    ahora = md(2026, 7, 26, 12, 0)
    asignados = [Interval("a", md(2026, 7, 26, 20, 0), md(2026, 7, 26, 22, 0))]
    filas = by_hour([], asignados, day=DIA, now=ahora)
    assert filas[20].assigned_count == 1
    assert filas[20].clocked_count is None
    assert filas[20].clocked_minutes is None


def test_a_started_hour_with_nobody_in_reports_zero_not_null() -> None:
    ahora = md(2026, 7, 26, 12, 0)
    asignados = [Interval("a", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 11, 0))]
    filas = by_hour([], asignados, day=DIA, now=ahora)
    assert filas[9].clocked_count == 0


def test_the_closing_shift_stays_with_its_business_day() -> None:
    # El turno de cierre del 26 sale de madrugada del 27 civil, pero es del
    # día 26: sus horas 0 y 1 acompañan a la venta de esa misma noche.
    fichajes = [Interval("a", md(2026, 7, 26, 23, 0), md(2026, 7, 27, 2, 0))]
    horas = [f.hour for f in hourly_staffing(fichajes, [], day=DIA, now=CERRADO)]
    assert horas == [23, 0, 1]


def test_the_next_business_day_does_not_steal_the_early_morning() -> None:
    # Esa misma madrugada NO aparece en el día 27: allí sería la gente de la
    # noche anterior junto a la venta de la noche siguiente.
    fichajes = [Interval("a", md(2026, 7, 26, 23, 0), md(2026, 7, 27, 2, 0))]
    filas = by_hour(fichajes, [], day=date(2026, 7, 27), now=CERRADO)
    assert filas == {}


def test_the_grid_of_a_business_day_ends_at_six_next_civil_day() -> None:
    # Las 05:59 del 27 civil aún son día 26; las 06:00 ya no.
    fichajes = [Interval("a", md(2026, 7, 27, 5, 0), md(2026, 7, 27, 7, 0))]
    filas26 = by_hour(fichajes, [], day=DIA, now=CERRADO)
    filas27 = by_hour(fichajes, [], day=date(2026, 7, 27), now=CERRADO)
    assert filas26[5].clocked_minutes == 60
    assert 6 not in filas26
    assert filas27[6].clocked_minutes == 60
    assert 5 not in filas27


def test_a_long_but_closed_punch_is_not_an_anomaly() -> None:
    # Solo preocupa el que sigue abierto: el cerrado ya tiene su salida real.
    fichajes = [Interval("a", md(2026, 7, 26, 7, 0), md(2026, 7, 26, 23, 0))]
    filas = by_hour(fichajes, [], day=DIA, now=CERRADO)
    assert all(f.open_anomalies == 0 for f in filas.values())


def test_minutes_are_never_negative() -> None:
    # Fichaje que empieza después de "ahora": no ha ocurrido nada.
    ahora = md(2026, 7, 26, 10, 0)
    fichajes = [Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 16, 0))]
    filas = hourly_staffing(fichajes, [], day=DIA, now=ahora)
    assert all(f.clocked_minutes is None or f.clocked_minutes >= 0 for f in filas)


def test_the_twenty_five_hour_day_of_october_neither_loses_nor_duplicates() -> None:
    # La madrugada del 25/10/2026 —cuando a las 03:00 el reloj vuelve a las
    # 02:00— pertenece al día de negocio 24. Su hora 2 dura el doble.
    dia = date(2026, 10, 24)
    tramo = Interval("a", md(2026, 10, 25, 0, 0), md(2026, 10, 25, 5, 0))
    filas = by_hour([tramo], [], day=dia, now=CERRADO)
    assert filas[2].clocked_minutes == 120  # la hora repetida
    assert sum(f.clocked_minutes or 0 for f in filas.values()) == 360


def test_the_twenty_three_hour_day_of_march_does_not_invent_the_missing_hour() -> None:
    # La madrugada del 29/03/2026 —cuando a las 02:00 el reloj salta a las
    # 03:00— pertenece al día de negocio 28. Su hora 2 no existe.
    dia = date(2026, 3, 28)
    tramo = Interval("a", md(2026, 3, 29, 0, 0), md(2026, 3, 29, 5, 0))
    filas = by_hour([tramo], [], day=dia, now=CERRADO)
    assert 2 not in filas
    assert sum(f.clocked_minutes or 0 for f in filas.values()) == 240


def test_both_feeds_live_in_the_same_hour() -> None:
    fichajes = [Interval("a", md(2026, 7, 26, 13, 0), md(2026, 7, 26, 14, 0))]
    asignados = [
        Interval("a", md(2026, 7, 26, 13, 0), md(2026, 7, 26, 14, 0)),
        Interval("b", md(2026, 7, 26, 13, 0), md(2026, 7, 26, 14, 0)),
    ]
    filas = by_hour(fichajes, asignados, day=DIA, now=CERRADO)
    assert (filas[13].clocked_count, filas[13].assigned_count) == (1, 2)


class TestCrewCounts:
    """Recuento sin dirección: lo que ve el gerente en la columna F/A.

    La dirección entra en el cuadrante con jornadas que no son un puesto en la
    línea, y mezclarlas con el equipo enturbia justo la pregunta que se hace
    quien mira la pantalla: ¿está cubierto el turno? Los recuentos totales se
    siguen guardando enteros —el VPHH se calcula con horas brutas de todos—,
    así que aquí conviven dos cifras por hora y ninguna sustituye a la otra.
    """

    def test_management_leaves_the_crew_count_but_not_the_total(self) -> None:
        fichajes = [
            Interval("gerente", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 11, 0)),
            Interval("equipo", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 11, 0)),
        ]
        filas = by_hour(fichajes, fichajes, day=DIA, now=CERRADO, crew=lambda p: p != "gerente")
        assert filas[9].clocked_count == 2
        assert filas[9].assigned_count == 2
        assert filas[9].crew_clocked_count == 1
        assert filas[9].crew_assigned_count == 1

    def test_crew_minutes_leave_out_management_too(self) -> None:
        fichajes = [
            Interval("gerente", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 10, 0)),
            Interval("equipo", md(2026, 7, 26, 9, 30), md(2026, 7, 26, 10, 0)),
        ]
        filas = by_hour(fichajes, fichajes, day=DIA, now=CERRADO, crew=lambda p: p != "gerente")
        assert filas[9].clocked_minutes == 90
        assert filas[9].crew_clocked_minutes == 30
        assert filas[9].crew_assigned_minutes == 30

    def test_without_a_crew_filter_the_crew_counts_are_null(self) -> None:
        # Si no se pudieron resolver los roles, no se sabe quién es equipo.
        # Repetir el total ahí colaría a la dirección haciéndola pasar por
        # equipo: la pantalla tiene que enseñar una raya, no una cifra falsa.
        fichajes = [Interval("a", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 10, 0))]
        filas = by_hour(fichajes, fichajes, day=DIA, now=CERRADO)
        assert filas[9].clocked_count == 1
        assert filas[9].crew_clocked_count is None
        assert filas[9].crew_assigned_count is None
        assert filas[9].crew_clocked_minutes is None
        assert filas[9].crew_assigned_minutes is None

    def test_an_hour_that_has_not_started_has_no_crew_punches_either(self) -> None:
        # Nulo por "aún no ha pasado", igual que el recuento total: un 0 diría
        # que no fichó nadie, que en una hora futura es sencillamente falso.
        asignados = [Interval("equipo", md(2026, 7, 26, 18, 0), md(2026, 7, 26, 20, 0))]
        filas = by_hour([], asignados, day=DIA, now=md(2026, 7, 26, 12), crew=lambda p: True)
        assert filas[18].clocked_count is None
        assert filas[18].crew_clocked_count is None
        assert filas[18].crew_assigned_count == 1

    def test_an_hour_with_only_management_still_shows_a_zero_crew(self) -> None:
        # Cero de verdad: la hora pasó y no había nadie de equipo. Distinto de
        # "no se sabe", y es exactamente el agujero de cobertura que se busca.
        fichajes = [Interval("gerente", md(2026, 7, 26, 7, 0), md(2026, 7, 26, 8, 0))]
        filas = by_hour(fichajes, fichajes, day=DIA, now=CERRADO, crew=lambda p: p != "gerente")
        assert filas[7].clocked_count == 1
        assert filas[7].crew_clocked_count == 0
        assert filas[7].crew_assigned_count == 0


class TestAssignedIsClippedToNow:
    """La hora EN CURSO se compara con lo que ya ha ocurrido, en los dos feeds.

    Contar los fichajes hasta ahora y el cuadrante de la hora entera crea una
    falsa ausencia cuando parte del turno empieza más tarde. La regla del
    módulo —nada que no haya ocurrido cuenta— vale para ambos feeds.

    Las horas FUTURAS son otra cosa: ahí la plantilla planificada completa es
    justo lo que se quiere ver, porque es lo que queda de día por cubrir.
    """

    def test_a_shift_starting_later_in_the_hour_is_not_missing_yet(self) -> None:
        # Son las 20:03 y el turno de noche entra a las 20:45: todavía no
        # falta nadie, y decir 1/2 sería acusar a quien llega puntual.
        ahora = md(2026, 7, 26, 20, 3)
        asignados = [
            Interval("tarde", md(2026, 7, 26, 16, 0), md(2026, 7, 26, 21, 0)),
            Interval("noche", md(2026, 7, 26, 20, 45), md(2026, 7, 26, 23, 0)),
        ]
        fichajes = [Interval("tarde", md(2026, 7, 26, 16, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[20].clocked_count == 1
        assert filas[20].assigned_count == 1

    def test_a_closed_hour_keeps_its_whole_roster(self) -> None:
        ahora = md(2026, 7, 26, 23, 0)
        asignados = [Interval("noche", md(2026, 7, 26, 20, 45), md(2026, 7, 26, 22, 0))]
        filas = by_hour([], asignados, day=DIA, now=ahora)
        assert filas[20].assigned_count == 1
        assert filas[20].assigned_minutes == 15

    def test_future_hours_keep_the_planned_roster(self) -> None:
        # Lo que queda de día por cubrir se sigue viendo entero: es lo que se
        # mira para decidir si hace falta llamar a alguien.
        ahora = md(2026, 7, 26, 12, 0)
        asignados = [Interval("noche", md(2026, 7, 26, 20, 0), md(2026, 7, 26, 23, 0))]
        filas = by_hour([], asignados, day=DIA, now=ahora)
        assert filas[20].assigned_count == 1
        assert filas[20].assigned_minutes == 60
        assert filas[22].assigned_count == 1

    def test_assigned_minutes_of_the_live_hour_stop_at_now(self) -> None:
        # Para que los minutos de las dos columnas cubran el mismo rato.
        ahora = md(2026, 7, 26, 14, 20)
        asignados = [Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0))]
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[14].clocked_minutes == 20
        assert filas[14].assigned_minutes == 20

    def test_a_real_absence_in_the_live_hour_still_shows(self) -> None:
        # Lo que NO puede pasar es tapar una ausencia de verdad: quien tenía
        # que estar desde el principio de la hora y no ha fichado, falta.
        ahora = md(2026, 7, 26, 14, 30)
        asignados = [
            Interval("presente", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0)),
            Interval("ausente", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0)),
        ]
        fichajes = [Interval("presente", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[14].clocked_count == 1
        assert filas[14].assigned_count == 2

    def test_the_crew_count_is_clipped_the_same_way(self) -> None:
        ahora = md(2026, 7, 26, 20, 3)
        asignados = [
            Interval("equipo", md(2026, 7, 26, 16, 0), md(2026, 7, 26, 21, 0)),
            Interval("noche", md(2026, 7, 26, 20, 45), md(2026, 7, 26, 23, 0)),
        ]
        filas = by_hour([], asignados, day=DIA, now=ahora, crew=lambda p: True)
        assert filas[20].crew_assigned_count == 1


class TestOpenPunchClipping:
    """El fichaje que nadie cierra deja de contar en su salida prevista.

    Un marcaje sin salida es presencia real mientras la persona está dentro, y
    deja de serlo en cuanto se va sin ficharla. Sin este corte, la columna F/A
    enseña gente que no está y esas horas acaban en el denominador del VPHH.
    """

    def test_an_open_punch_stops_at_the_planned_departure(self) -> None:
        # Entra a las 14:00 con turno hasta las 18:00 y no ficha la salida. A
        # las 22:00 no puede seguir contando: se fue a las 18:00.
        ahora = md(2026, 7, 26, 22, 0)
        asignados = [Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0))]
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[17].clocked_minutes == 60
        assert filas[18].clocked_minutes == 30  # los 30 min de cortesía
        assert 19 not in filas or filas[19].clocked_count == 0

    def test_someone_still_inside_before_their_shift_ends_counts_whole(self) -> None:
        # La regla no puede recortar a quien está trabajando.
        ahora = md(2026, 7, 26, 16, 30)
        asignados = [Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0))]
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[16].clocked_minutes == 30
        assert filas[15].clocked_count == 1

    def test_an_open_punch_without_a_shift_is_capped_at_ten_hours(self) -> None:
        # Quien no figura en el cuadrante ese día —un refuerzo, un cambio de
        # última hora— no tiene salida prevista de la que colgar el corte, así
        # que se aplica el máximo defensivo.
        ahora = md(2026, 7, 27, 5, 0)
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, [], day=DIA, now=ahora)
        assert filas[23].clocked_minutes == 60
        assert 0 not in filas or filas[0].clocked_count == 0

    def test_the_cap_never_overrides_an_earlier_planned_departure(self) -> None:
        # Con turno corto manda el cuadrante, no el tope: gana el más temprano.
        ahora = md(2026, 7, 27, 5, 0)
        asignados = [Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 17, 0))]
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[17].clocked_minutes == 30
        assert 18 not in filas or filas[18].clocked_count == 0

    def test_a_closed_punch_is_never_clipped(self) -> None:
        # Un checkOut explícito manda sobre el límite defensivo de abiertos.
        asignados = [Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 17, 0))]
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 19, 0))]
        filas = by_hour(fichajes, asignados, day=DIA, now=CERRADO)
        assert filas[18].clocked_minutes == 60
        assert sum(f.clocked_minutes or 0 for f in filas.values()) == 300

    def test_a_split_shift_is_not_cut_at_the_midday_gap(self) -> None:
        # El fichaje de la tarde se cuelga del tramo de la tarde: quien libra de
        # 12:00 a 17:00 y vuelve por la noche no se va al mediodía.
        ahora = md(2026, 7, 27, 5, 0)
        asignados = [
            Interval("a", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 12, 0)),
            Interval("a", md(2026, 7, 26, 17, 0), md(2026, 7, 26, 21, 0)),
        ]
        fichajes = [Interval("a", md(2026, 7, 26, 17, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[20].clocked_minutes == 60
        assert filas[21].clocked_minutes == 30

    def test_an_open_punch_stops_when_the_same_person_punches_in_again(self) -> None:
        # Turno seguido de 09:00 a 21:00, un solo tramo de cuadrante: se deja
        # abierto el fichaje de la mañana y se vuelve a fichar a las 13:00,
        # dentro del propio turno. Aquí la salida prevista de los DOS fichajes
        # es la misma —las 21:00—, así que el único tope que separa el abierto
        # del bueno es la segunda entrada. Sin él, el abierto llegaría a las
        # 19:00 por el tope de 10 h y se solaparía consigo mismo: las horas 13
        # a 18 declararían 120 minutos dentro de una hora de 60, un número
        # físicamente imposible en el denominador del VPHH.
        asignados = [Interval("a", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 21, 0))]
        fichajes = [
            Interval("a", md(2026, 7, 26, 9, 0), None),
            Interval("a", md(2026, 7, 26, 13, 0), md(2026, 7, 26, 21, 0)),
        ]
        filas = by_hour(fichajes, asignados, day=DIA, now=CERRADO)
        assert all((f.clocked_minutes or 0) <= 60 for f in filas.values())
        # Una persona, una hora: nadie puede estar dos veces dentro de la misma.
        assert filas[14].clocked_minutes == 60
        assert filas[14].clocked_count == 1
        # El abierto cuenta de 09:00 a 13:00 y el cerrado sus ocho horas: 12 h.
        assert sum(f.clocked_minutes or 0 for f in filas.values()) == 720

    def test_a_split_shift_left_open_stops_at_the_end_of_its_own_segment(self) -> None:
        # Un marcaje abierto se limita al tramo que contiene su entrada; los
        # tramos posteriores del cuadrante no prolongan esa presencia.
        asignados = [
            Interval("a", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 12, 0)),
            Interval("a", md(2026, 7, 26, 17, 0), md(2026, 7, 26, 21, 0)),
        ]
        fichajes = [Interval("a", md(2026, 7, 26, 9, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=CERRADO)
        assert filas[12].clocked_minutes == 30
        assert sum(f.clocked_minutes or 0 for f in filas.values()) == 210
        # La tarde no cuenta a nadie: el turno de 17-21 sigue asignado, pero
        # ahí no ha fichado ninguna persona.
        assert all(filas[h].clocked_count == 0 for h in range(13, 22) if h in filas)
        assert filas[17].assigned_count == 1
        # Y el recorte se ve desde la hora en que cae, no desde el cierre.
        assert filas[12].open_anomalies == 1
        assert filas[9].open_anomalies == 0

    def test_a_split_shift_with_both_punches_counts_the_real_minutes(self) -> None:
        # Cada entrada se vincula a su propio tramo; el hueco entre ambos no
        # forma parte del tiempo trabajado.
        asignados = [
            Interval("a", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 12, 0)),
            Interval("a", md(2026, 7, 26, 17, 0), md(2026, 7, 26, 21, 0)),
        ]
        fichajes = [
            Interval("a", md(2026, 7, 26, 9, 0), None),
            Interval("a", md(2026, 7, 26, 17, 0), md(2026, 7, 26, 21, 0)),
        ]
        filas = by_hour(fichajes, asignados, day=DIA, now=CERRADO)
        assert all((f.clocked_minutes or 0) <= 60 for f in filas.values())
        assert sum(f.clocked_minutes or 0 for f in filas.values()) == 210 + 240
        assert filas[12].clocked_minutes == 30
        assert filas[13].clocked_count == 0
        assert filas[17].clocked_minutes == 60
        assert filas[20].clocked_minutes == 60

    def test_contiguous_roster_segments_are_one_shift(self) -> None:
        # la fuente de personal entrega un tramo por marco de TAREA, no por turno: una
        # jornada corrida llega en tramos pegados cuando cambia la tarea.
        # Cortar ahí inventaría una ausencia a las 13:30 de alguien que está
        # trabajando: la salida prevista son las 17:00, y el corte, las 17:30.
        asignados = [
            Interval("a", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 13, 0)),
            Interval("a", md(2026, 7, 26, 13, 0), md(2026, 7, 26, 17, 0)),
        ]
        fichajes = [Interval("a", md(2026, 7, 26, 9, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=CERRADO)
        assert filas[13].clocked_minutes == 60
        assert filas[17].clocked_minutes == 30
        assert sum(f.clocked_minutes or 0 for f in filas.values()) == 510
        # Y nada que marcar mientras dura la jornada: sin la fusión, las horas
        # de 13:00 en adelante llevarían el aviso del recorte.
        assert all(filas[h].open_anomalies == 0 for h in range(9, 17) if h in filas)

    def test_a_forty_five_minute_break_does_not_split_the_shift(self) -> None:
        # Un descanso acotado deja hueco entre tramos, pero sigue perteneciendo
        # al mismo bloque de jornada.
        asignados = [
            Interval("a", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 13, 0)),
            Interval("a", md(2026, 7, 26, 13, 45), md(2026, 7, 26, 17, 0)),
        ]
        fichajes = [Interval("a", md(2026, 7, 26, 9, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=CERRADO)
        assert filas[13].clocked_minutes == 60
        assert filas[17].clocked_minutes == 30
        assert sum(f.clocked_minutes or 0 for f in filas.values()) == 510

    def test_a_four_hour_gap_is_a_real_split_shift(self) -> None:
        # Un hueco amplio no es un cambio de tarea ni una comida: es un
        # turno partido.
        # El marcaje de la mañana termina en su tramo: 12:00 más la cortesía.
        asignados = [
            Interval("a", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 12, 0)),
            Interval("a", md(2026, 7, 26, 16, 0), md(2026, 7, 26, 20, 0)),
        ]
        fichajes = [Interval("a", md(2026, 7, 26, 9, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=CERRADO)
        assert filas[12].clocked_minutes == 30
        assert sum(f.clocked_minutes or 0 for f in filas.values()) == 210
        assert filas[12].open_anomalies == 1

    def test_a_gap_just_under_the_threshold_merges(self) -> None:
        # 1 h 59 min: por debajo de las dos horas, misma jornada. La frontera
        # se fija aquí y en el test de al lado para que un cambio del umbral no
        # pase inadvertido.
        asignados = [
            Interval("a", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 12, 0)),
            Interval("a", md(2026, 7, 26, 13, 59), md(2026, 7, 26, 18, 0)),
        ]
        fichajes = [Interval("a", md(2026, 7, 26, 9, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=CERRADO)
        assert filas[13].clocked_minutes == 60
        assert filas[18].clocked_minutes == 30
        assert sum(f.clocked_minutes or 0 for f in filas.values()) == 570

    def test_a_gap_at_the_threshold_does_not_merge(self) -> None:
        # Dos horas exactas ya no se fusionan: el umbral es estricto, y ese es
        # el lado seguro —por encima manda el tramo propio de cada fichaje—.
        asignados = [
            Interval("a", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 12, 0)),
            Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0)),
        ]
        fichajes = [Interval("a", md(2026, 7, 26, 9, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=CERRADO)
        assert filas[12].clocked_minutes == 30
        assert sum(f.clocked_minutes or 0 for f in filas.values()) == 210

    def test_the_cap_rules_when_no_segment_ends_after_the_punch_in(self) -> None:
        # Ficha a las 13:00 cuando su único tramo del día terminó a las 12:00:
        # un refuerzo que entra después de su cuadrante, o un cambio que la fuente de personal
        # no llegó a reflejar. No hay salida prevista de la que colgar el corte
        # —el tramo de la mañana no dice nada de este fichaje—, así que manda el
        # tope de 10 h: las 23:00.
        ahora = md(2026, 7, 27, 5, 0)
        asignados = [Interval("a", md(2026, 7, 26, 9, 0), md(2026, 7, 26, 12, 0))]
        fichajes = [Interval("a", md(2026, 7, 26, 13, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[13].clocked_minutes == 60
        assert filas[22].clocked_minutes == 60
        assert 23 not in filas or filas[23].clocked_count == 0
        assert sum(f.clocked_minutes or 0 for f in filas.values()) == 600

    def test_an_open_punch_with_no_later_punch_of_that_person_is_clipped_as_before(self) -> None:
        # El tope nuevo mira solo los fichajes de ESA persona: el de otra, por
        # posterior que sea, no recorta nada. "a" sigue cortándose en su salida
        # prevista más la cortesía, a las 18:30.
        ahora = md(2026, 7, 26, 22, 0)
        asignados = [Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0))]
        fichajes = [
            Interval("a", md(2026, 7, 26, 14, 0), None),
            Interval("b", md(2026, 7, 26, 15, 0), md(2026, 7, 26, 20, 0)),
        ]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[18].clocked_minutes == 90  # los 30 de cortesía de "a" y la hora de "b"
        assert filas[19].clocked_count == 1  # solo "b": el abierto ya no cuenta
        assert filas[21].open_anomalies == 1

    def test_an_open_overnight_punch_is_capped(self) -> None:
        # Un turno nocturno abierto deja de contar tras su salida prevista.
        ahora = md(2026, 7, 27, 8, 0)
        asignados = [Interval("a", md(2026, 7, 26, 20, 0), md(2026, 7, 27, 1, 30))]
        fichajes = [Interval("a", md(2026, 7, 26, 20, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[1].clocked_minutes == 60
        assert 2 not in filas or filas[2].clocked_minutes == 0
        assert all(filas[h].clocked_count == 0 for h in (3, 4, 5) if h in filas)

    def test_a_schedule_segment_outside_the_grid_does_not_move_the_departure(self) -> None:
        # Los tramos fuera de la rejilla de negocio no pueden mover la salida
        # efectiva de un marcaje incluido en ella.
        ahora = md(2026, 7, 26, 22, 0)
        asignados = [
            Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0)),
            Interval("a", md(2026, 7, 28, 10, 0), md(2026, 7, 28, 14, 0)),
        ]
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[17].clocked_minutes == 60
        assert filas[18].clocked_minutes == 30  # los 30 min de cortesía
        assert 19 not in filas or filas[19].clocked_count == 0

    def test_a_schedule_segment_from_the_night_before_does_not_erase_the_punch(self) -> None:
        # La otra mitad del mismo filtro: un tramo de la VÍSPERA que termina
        # antes de que abra la rejilla. Aquí es el ÚNICO tramo que llega para
        # esta persona —sin ningún tramo del propio día 26—, que es a
        # propósito: un tramo anterior a la apertura no puede convertirse en
        # la salida prevista de una entrada posterior.
        ahora = md(2026, 7, 26, 16, 0)
        asignados = [Interval("a", md(2026, 7, 25, 22, 0), md(2026, 7, 26, 2, 0))]
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[14].clocked_minutes == 60
        assert filas[15].clocked_minutes == 60

    def test_the_clip_lands_on_the_real_instant_not_the_wall_clock(self) -> None:
        # La madrugada del 25/10/2026 vive las 02:00-03:00 dos veces. Aquí el
        # turno termina justo al empezar la SEGUNDA vez (fold=1: son las
        # 01:00 UTC, no las 00:00 que saldrían de tomar la primera). El corte
        # cae 30 min después, a la 01:30 UTC: 90 de los 120 minutos reales de
        # esa hora repetida. Sumar la cortesía en hora de Madrid en vez de en
        # UTC daría 00:30 y solo 30 minutos — mal por una hora entera, y sin
        # levantar ninguna excepción, que es justo el fallo que este módulo
        # existe para evitar.
        dia = date(2026, 10, 24)
        entrada = md(2026, 10, 24, 20, 0)
        fin_turno = datetime(2026, 10, 25, 2, 0, tzinfo=MADRID, fold=1)
        ahora = md(2026, 10, 25, 9, 0)
        asignados = [Interval("a", entrada, fin_turno)]
        fichajes = [Interval("a", entrada, None)]
        filas = by_hour(fichajes, asignados, day=dia, now=ahora)
        assert filas[2].clocked_minutes == 90
        assert 3 not in filas or filas[3].clocked_count == 0
        assert sum(f.clocked_minutes or 0 for f in filas.values()) == 450

    def test_the_crew_count_is_clipped_at_the_planned_departure_too(self) -> None:
        # El recuento de equipo sale de los mismos minutos: si no se recortara
        # igual, la cifra que se enseña seguiría siendo la falsa.
        ahora = md(2026, 7, 26, 22, 0)
        asignados = [Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0))]
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora, crew=lambda _: True)
        assert filas[18].crew_clocked_minutes == 30
        assert 19 not in filas or filas[19].crew_clocked_count == 0


class TestClippedPunchesAreVisible:
    """Un dato corregido tiene que verse, igual que la marca de frescura.

    ``open_anomalies`` cuenta los fichajes abiertos que se están ignorando en
    esa hora: si la columna F/A enseña una persona menos porque nadie cerró un
    marcaje, quien mira la pantalla tiene derecho a saberlo.
    """

    def test_the_hours_after_the_clip_are_flagged(self) -> None:
        ahora = md(2026, 7, 26, 22, 0)
        asignados = [Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0))]
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[18].open_anomalies == 1
        assert filas[21].open_anomalies == 1

    def test_the_hours_before_the_clip_are_not_flagged(self) -> None:
        # Mientras estaba dentro no se corrigió nada: no hay nada que marcar.
        ahora = md(2026, 7, 26, 22, 0)
        asignados = [Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0))]
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[14].open_anomalies == 0
        assert filas[17].open_anomalies == 0

    def test_someone_still_inside_is_not_flagged(self) -> None:
        ahora = md(2026, 7, 26, 16, 30)
        asignados = [Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0))]
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert all(f.open_anomalies == 0 for f in filas.values())

    def test_two_clipped_punches_count_two(self) -> None:
        ahora = md(2026, 7, 26, 22, 0)
        asignados = [
            Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0)),
            Interval("b", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0)),
        ]
        fichajes = [
            Interval("a", md(2026, 7, 26, 14, 0), None),
            Interval("b", md(2026, 7, 26, 14, 0), None),
        ]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[21].open_anomalies == 2

    def test_a_future_hour_is_not_flagged(self) -> None:
        # Una hora que no ha llegado no puede tener nada corregido.
        ahora = md(2026, 7, 26, 22, 0)
        asignados = [
            Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0)),
            Interval("noche", md(2026, 7, 27, 0, 0), md(2026, 7, 27, 3, 0)),
        ]
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[0].open_anomalies == 0

    def test_management_does_not_flag_the_crew_figure(self) -> None:
        # La pantalla pinta el recuento de equipo: el aviso tiene que contar
        # sobre esa misma población. Un gerente que se deja el fichaje abierto
        # no corrige nada de lo que se ve, y marcarlo diría "esto no es una
        # ausencia" en una hora en la que sí puede haberla.
        ahora = md(2026, 7, 26, 22, 0)
        asignados = [Interval("gerente", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0))]
        fichajes = [Interval("gerente", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora, crew=lambda p: p != "gerente")
        assert filas[21].open_anomalies == 1
        assert filas[21].crew_open_anomalies == 0

    def test_a_clipped_crew_punch_flags_both_counts(self) -> None:
        ahora = md(2026, 7, 26, 22, 0)
        asignados = [Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0))]
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora, crew=lambda p: p != "gerente")
        assert filas[21].open_anomalies == 1
        assert filas[21].crew_open_anomalies == 1

    def test_without_a_crew_filter_the_crew_flag_is_null(self) -> None:
        # Sin roles no se sabe a quién se recortó: un 0 diría "no hay ningún
        # fichaje sin cerrar", que es otra afirmación.
        ahora = md(2026, 7, 26, 22, 0)
        asignados = [Interval("a", md(2026, 7, 26, 14, 0), md(2026, 7, 26, 18, 0))]
        fichajes = [Interval("a", md(2026, 7, 26, 14, 0), None)]
        filas = by_hour(fichajes, asignados, day=DIA, now=ahora)
        assert filas[21].open_anomalies == 1
        assert filas[21].crew_open_anomalies is None


class TestSettledHours:
    """Qué horas del día de negocio han cerrado ya, vistas desde un instante.

    Sirve para preguntarle a la rejilla "¿esto ya debería haber ocurrido?" sin
    que quien pregunta tenga que saber que la fila 2 de un día es la madrugada
    del día civil siguiente.
    """

    def test_only_hours_already_closed_are_settled(self) -> None:
        asentadas = hours_settled_by(DIA, md(2026, 7, 26, 9, 30))
        assert 8 in asentadas  # cerró a las 09:00
        assert 9 not in asentadas  # está en curso
        assert 10 not in asentadas

    def test_the_small_hours_belong_to_the_next_calendar_day(self) -> None:
        # La fila 2 del día 26 es la madrugada que CIERRA el 26, ya del día 27.
        asentadas = hours_settled_by(DIA, md(2026, 7, 27, 3, 0))
        assert 2 in asentadas
        assert 3 not in asentadas
        # Y a las 03:00 del propio día 26 no había cerrado nada todavía.
        assert 2 not in hours_settled_by(DIA, md(2026, 7, 26, 3, 0))

    def test_nothing_is_settled_when_the_day_opens(self) -> None:
        assert hours_settled_by(DIA, md(2026, 7, 26, 6, 0)) == set()

    def test_a_closed_day_has_all_its_hours_settled(self) -> None:
        assert len(hours_settled_by(DIA, CERRADO)) == 24
