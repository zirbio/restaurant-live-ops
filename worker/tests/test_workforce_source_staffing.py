"""Lectura de fichajes y cuadrante contra payloads completamente sintéticos."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from restaurant_live_ops.workforce_source.staffing import (
    assignments_path,
    clockguards_path,
    parse_assignments,
    parse_clockguards,
)

FIXTURES = Path(__file__).parent / "fixtures" / "workforce"


def load(nombre: str) -> list[dict[str, Any]]:
    datos: list[dict[str, Any]] = json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))
    return datos


def test_paths_match_the_manual() -> None:
    assert clockguards_path("BIZ-TEST", "R001", date(2030, 1, 15)) == (
        "/importer/api/v2/businesses/BIZ-TEST/services/R001"
        "/clockguards?from=2030-01-15&to=2030-01-15"
    )
    assert assignments_path("BIZ-TEST", "R001", date(2030, 1, 15)) == (
        "/importer/api/v1/business/BIZ-TEST/service/R001/assignments/from/2030-01-15/to/2030-01-15"
    )


def test_the_synthetic_punch_is_read_whole() -> None:
    crudo = load("clockguards.json")
    tramos = parse_clockguards(crudo)
    trabajo = [f for f in crudo if f.get("type") == "WORK"]
    assert len(tramos) == len(trabajo)
    assert all(t.start.tzinfo is not None for t in tramos)


def test_utc_marks_are_converted_to_madrid() -> None:
    # 00:00Z del 29/03/2026 es la 01:00 de Madrid (aún horario de invierno).
    tramos = parse_clockguards(
        [
            {
                "employeeId": "EMP_001",
                "type": "WORK",
                "checkIn": "2026-03-29T00:00:00.000Z",
                "checkOut": "2026-03-29T02:30:00.000Z",
            }
        ]
    )
    assert tramos[0].start.hour == 1


def test_only_work_counts_not_breaks() -> None:
    tramos = parse_clockguards(
        [
            {
                "employeeId": "EMP_001",
                "type": "REST",
                "checkIn": "2026-07-26T09:00:00.000Z",
                "checkOut": "2026-07-26T09:30:00.000Z",
            },
            {
                "employeeId": "EMP_002",
                "type": "WORK",
                "checkIn": "2026-07-26T09:00:00.000Z",
                "checkOut": "2026-07-26T17:00:00.000Z",
            },
        ]
    )
    assert [t.person for t in tramos] == ["EMP_002"]


def test_a_punch_without_checkout_stays_open() -> None:
    tramos = parse_clockguards(
        [{"employeeId": "EMP_001", "type": "WORK", "checkIn": "2026-07-26T11:00:00.000Z"}]
    )
    assert tramos[0].end is None


def test_a_checkout_before_the_checkin_is_dropped() -> None:
    # La API devuelve los registros tal como se grabaron, pares mal
    # emparejados incluidos. Un tramo negativo restaría presencia.
    tramos = parse_clockguards(
        [
            {
                "employeeId": "EMP_001",
                "type": "WORK",
                "checkIn": "2026-07-26T17:00:00.000Z",
                "checkOut": "2026-07-26T09:00:00.000Z",
            }
        ]
    )
    assert tramos == []


def test_the_synthetic_roster_exposes_the_expected_interval() -> None:
    filas = load("assignments.json")
    tramos = parse_assignments(filas)
    assert len(tramos) == 1
    assert tramos[0].person == "EMP-TEST-001"
    assert (tramos[0].start.hour, tramos[0].end and tramos[0].end.hour) == (8, 9)


def test_a_day_off_in_the_synthetic_roster_does_not_count() -> None:
    tramos = parse_assignments(load("assignments.json"))

    assert {tramo.person for tramo in tramos} == {"EMP-TEST-001"}


def test_a_frame_crossing_midnight_ends_the_next_day() -> None:
    # startMinuteDay 1380 = 23:00; 300 minutos llevan a las 04:00 del día 27.
    tramos = parse_assignments(
        [
            {
                "person": "EMP_001",
                "day": "2026-07-26",
                "virtual": False,
                "presence": {
                    "worked": True,
                    "timeFrames": [
                        {
                            "startMinuteDay": 1380,
                            "duration": 300,
                            "paid": True,
                            "worked": True,
                            "location": {"name": "Cierre"},
                        }
                    ],
                },
            }
        ]
    )
    assert tramos[0].start.day == 26
    assert tramos[0].end is not None
    assert tramos[0].end.day == 27
    assert tramos[0].end.hour == 4


def test_unpaid_frames_do_not_count() -> None:
    tramos = parse_assignments(
        [
            {
                "person": "EMP_001",
                "day": "2026-07-26",
                "virtual": False,
                "presence": {
                    "worked": True,
                    "timeFrames": [
                        {
                            "startMinuteDay": 540,
                            "duration": 60,
                            "paid": False,
                            "worked": True,
                            "location": {"name": "Comida"},
                        }
                    ],
                },
            }
        ]
    )
    assert tramos == []


def test_virtual_employees_do_not_count() -> None:
    tramos = parse_assignments(
        [
            {
                "person": "EMP_001",
                "day": "2026-07-26",
                "virtual": True,
                "presence": {
                    "worked": True,
                    "timeFrames": [
                        {
                            "startMinuteDay": 540,
                            "duration": 480,
                            "paid": True,
                            "worked": True,
                            "location": {"name": "Cajero"},
                        }
                    ],
                },
            }
        ]
    )
    assert tramos == []


def test_committee_hours_count_as_assigned() -> None:
    # Horas brutas: el comité no se descuenta. Aparece como cualquier tarea.
    tramos = parse_assignments(
        [
            {
                "person": "EMP_001",
                "day": "2026-07-26",
                "virtual": False,
                "presence": {
                    "worked": True,
                    "timeFrames": [
                        {
                            "startMinuteDay": 540,
                            "duration": 360,
                            "paid": True,
                            "worked": True,
                            "location": {"name": "Comité"},
                        }
                    ],
                },
            }
        ]
    )
    assert len(tramos) == 1
