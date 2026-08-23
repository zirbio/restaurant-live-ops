"""Quién cuenta como dotación de turno y quién es dirección.

El rol no viaja con el fichaje ni con el cuadrante: hay que leerlo del
contrato vigente de cada persona. Todo lo que se prueba aquí decide qué
personas entran en el recuento que ve el gerente, así que un fallo silencioso
aquí sale por pantalla como una plantilla que no existió.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import pytest

from restaurant_live_ops.workforce_source.roles import (
    MANAGEMENT_CATEGORIES,
    active_person_category,
    crew_filter,
    fetch_person_categories,
    match_people_by_name,
    resolve_crew,
)

HOY = date(2026, 7, 28)


def contrato(desde: str | None, hasta: str | None, categoria: str) -> dict[str, object]:
    fila: dict[str, object] = {"personCategory": categoria}
    if desde is not None:
        fila["from"] = desde
    if hasta is not None:
        fila["to"] = hasta
    return fila


class TestActiveCategory:
    def test_the_contract_in_force_today_wins(self) -> None:
        assert (
            active_person_category(
                [contrato("2024-01-01", "2026-04-30", "013"), contrato("2026-05-01", None, "010")],
                on=HOY,
            )
            == "010"
        )

    def test_a_future_contract_never_hijacks_the_role(self) -> None:
        # Un contrato futuro no describe el rol vigente; el orden de la
        # respuesta no puede darle prioridad.
        assert (
            active_person_category(
                [contrato("2026-09-01", None, "013"), contrato("2026-05-01", None, "010")],
                on=HOY,
            )
            == "010"
        )

    def test_a_finished_contract_does_not_count(self) -> None:
        assert active_person_category([contrato("2024-01-01", "2026-06-30", "003")], on=HOY) is None

    def test_when_several_overlap_the_most_recent_start_wins(self) -> None:
        assert (
            active_person_category(
                [contrato("2026-01-01", None, "013"), contrato("2026-07-01", None, "006")],
                on=HOY,
            )
            == "006"
        )

    def test_no_contract_is_not_a_role(self) -> None:
        # Sin contrato vigente no se sabe el rol. Devolver "013" de relleno
        # colaría a un gerente en el recuento de equipo.
        assert active_person_category([], on=HOY) is None
        assert active_person_category([contrato(None, None, "013")], on=HOY) == "013"


class TestCrewFilter:
    def test_management_does_not_count_as_crew(self) -> None:
        es_equipo = crew_filter({"P1": "003", "P2": "001", "P3": "002", "P4": "013"}, excluded=())
        assert not es_equipo("P1")  # Gerente
        assert not es_equipo("P2")  # Supervisor
        assert not es_equipo("P3")  # Franquiciado
        assert es_equipo("P4")  # Personal de equipo

    def test_shift_managers_are_crew(self) -> None:
        # Asistentes, encargados de turno y de área forman parte de la dotación
        # operativa y, por tanto, cuentan.
        es_equipo = crew_filter(
            {"P1": "004", "P2": "005", "P3": "006", "P4": "007", "P5": "012", "P6": "010"},
            excluded=(),
        )
        assert all(es_equipo(p) for p in ("P1", "P2", "P3", "P4", "P5", "P6"))

    def test_named_exclusions_are_dropped_whatever_their_role(self) -> None:
        # Una persona excluida puede compartir categoría con quienes sí hacen
        # turno, por lo que la exclusión nominal prevalece sobre el rol.
        es_equipo = crew_filter({"P1": "010", "P2": "010"}, excluded=("P2",))
        assert es_equipo("P1")
        assert not es_equipo("P2")

    def test_an_unknown_person_is_not_guessed(self) -> None:
        # Quien ficha sin categoría conocida no se puede clasificar. Contarlo
        # como equipo sería inventarse el dato.
        es_equipo = crew_filter({"P1": "013"}, excluded=())
        with pytest.raises(KeyError):
            es_equipo("FANTASMA")


class TestNameMatching:
    def test_the_full_name_is_matched_ignoring_case_and_accents(self) -> None:
        empleados = [
            {"employeeId": "EMP-TEST-010", "name": "Alicia", "surname": "Prueba Norte"},
            {"employeeId": "EMP-TEST-011", "name": "Alicia", "surname": "Prueba Sur"},
        ]
        casados, sin_casar = match_people_by_name(empleados, ("alicia prueba norte",))
        assert casados == {"EMP-TEST-010"}
        assert sin_casar == ()

    def test_extra_whitespace_does_not_break_the_match(self) -> None:
        empleados = [{"employeeId": "EMP-TEST-012", "name": " Alicia ", "surname": "Prueba  Norte"}]
        casados, _ = match_people_by_name(empleados, ("Alicia Prueba Norte",))
        assert casados == {"EMP-TEST-012"}

    def test_a_name_that_matches_nobody_is_reported_not_ignored(self) -> None:
        # la fuente de personal renumera y reescribe fichas. Una exclusión que deja de casar
        # tiene que verse: si no, el mando vuelve al recuento en silencio.
        empleados = [{"employeeId": "EMP-TEST-010", "name": "Alicia", "surname": "Prueba Norte"}]
        casados, sin_casar = match_people_by_name(
            empleados, ("Alicia Prueba Norte", "Persona Ficticia Ausente")
        )
        assert casados == {"EMP-TEST-010"}
        assert len(sin_casar) == 1

    def test_the_unmatched_report_never_carries_the_name(self) -> None:
        # El aviso viaja a los logs del ciclo: ahí no puede ir un nombre.
        _, sin_casar = match_people_by_name([], ("Alicia Prueba Norte",))
        assert all("alicia" not in str(x).lower() for x in sin_casar)

    def test_virtual_employees_are_never_matched(self) -> None:
        empleados = [
            {
                "employeeId": "EMP-TEST-VIRTUAL",
                "name": "Alicia",
                "surname": "Prueba Norte",
                "virtual": True,
            }
        ]
        casados, _ = match_people_by_name(empleados, ("Alicia Prueba Norte",))
        assert casados == set()


def test_management_categories_are_the_three_agreed() -> None:
    # Supervisor de operaciones, franquiciado y gerente. Ni uno más: la
    # decisión de qué queda fuera del recuento es de negocio, no técnica.
    assert MANAGEMENT_CATEGORIES == frozenset({"001", "002", "003"})


class TestResolveCrew:
    """Qué pasa cuando no se puede clasificar a todo el mundo.

    Un contrato caducado o un fallo a mitad del endpoint dejan gente sin
    categoría. Contarla como equipo sería inventarse el rol, y hacer fallar el
    restaurante entero perdería también los recuentos totales, que sí son
    buenos. Se renuncia al recuento de equipo de ese local —la pantalla enseña
    una raya— y el hueco se cuenta para que salga en el log del ciclo.
    """

    def test_with_everyone_classified_there_is_a_filter(self) -> None:
        es_equipo, sin_clasificar = resolve_crew(
            {"P1": "003", "P2": "013"}, people=("P1", "P2"), excluded=()
        )
        assert sin_clasificar == 0
        assert es_equipo is not None
        assert not es_equipo("P1")
        assert es_equipo("P2")

    def test_one_person_without_a_role_drops_the_whole_count(self) -> None:
        es_equipo, sin_clasificar = resolve_crew({"P1": "013"}, people=("P1", "P2"), excluded=())
        assert es_equipo is None
        assert sin_clasificar == 1

    def test_an_excluded_person_needs_no_category(self) -> None:
        # A quien se descuenta por nombre le da igual el contrato: ya está
        # fuera, y su falta de categoría no puede tumbar el recuento del local.
        es_equipo, sin_clasificar = resolve_crew(
            {"P1": "013"}, people=("P1", "P2"), excluded=("P2",)
        )
        assert sin_clasificar == 0
        assert es_equipo is not None
        assert not es_equipo("P2")

    def test_nobody_at_all_still_yields_a_filter(self) -> None:
        # Un día sin turnos no es un fallo de clasificación.
        es_equipo, sin_clasificar = resolve_crew({}, people=(), excluded=())
        assert sin_clasificar == 0
        assert es_equipo is not None


async def test_person_category_fanout_is_bounded_before_any_request() -> None:
    class RecordingClient:
        def __init__(self) -> None:
            self.paths: list[str] = []

        async def get_json(self, path: str) -> list[dict[str, object]]:
            self.paths.append(path)
            return []

    client = RecordingClient()

    with pytest.raises(ValueError, match="límite de personas"):
        await fetch_person_categories(
            client,  # type: ignore[arg-type]
            business_id="BIZ-TEST",
            people=(f"PERSON-{index}" for index in range(501)),
            on=HOY,
        )

    assert client.paths == []


async def test_person_limit_stops_consuming_the_input_at_the_first_excess() -> None:
    class RecordingClient:
        async def get_json(self, path: str) -> list[dict[str, object]]:
            raise AssertionError(f"no debe pedir contratos: {path}")

    def guarded_people() -> Iterable[str]:
        for index in range(501):
            yield f"PERSON-{index}"
        raise AssertionError("el límite debe cortar sin materializar el resto")

    with pytest.raises(ValueError, match="límite de personas"):
        await fetch_person_categories(
            RecordingClient(),  # type: ignore[arg-type]
            business_id="BIZ-TEST",
            people=guarded_people(),
            on=HOY,
        )
