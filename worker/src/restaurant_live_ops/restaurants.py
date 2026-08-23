"""Restaurantes definidos por la configuración de cada instalación."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Restaurant:
    id: str
    name: str
    source_site: str
    display_order: int
    has_drive_through: bool
    workforce_expected_hours: tuple[int, ...] = ()


def _required_text(item: dict[str, object], field: str, position: int) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"RESTAURANTS_JSON elemento {position}: {field} debe ser texto no vacío")
    return value.strip()


def _restaurant_from_item(item: object, position: int) -> Restaurant:
    if not isinstance(item, dict):
        raise RuntimeError(f"RESTAURANTS_JSON elemento {position} debe ser un objeto")

    has_drive_through = item.get("has_drive_through")
    if type(has_drive_through) is not bool:
        raise RuntimeError(
            f"RESTAURANTS_JSON elemento {position}: has_drive_through debe ser booleano"
        )

    display_order = item.get("display_order")
    if type(display_order) is not int:
        raise RuntimeError(
            f"RESTAURANTS_JSON elemento {position}: display_order debe ser un entero"
        )

    expected_hours = item.get("workforce_expected_hours")
    if (
        not isinstance(expected_hours, list)
        or not expected_hours
        or any(type(hour) is not int or hour < 0 or hour > 23 for hour in expected_hours)
        or len(set(expected_hours)) != len(expected_hours)
    ):
        raise RuntimeError(
            f"RESTAURANTS_JSON elemento {position}: workforce_expected_hours "
            "debe ser una lista no vacía de horas únicas entre 0 y 23"
        )

    return Restaurant(
        id=_required_text(item, "id", position),
        name=_required_text(item, "name", position),
        source_site=_required_text(item, "source_site", position),
        display_order=display_order,
        has_drive_through=has_drive_through,
        workforce_expected_hours=tuple(expected_hours),
    )


def restaurants_from_env() -> tuple[Restaurant, ...]:
    raw = os.getenv("RESTAURANTS_JSON")
    if not raw:
        raise RuntimeError("falta la variable de entorno RESTAURANTS_JSON")
    try:
        items: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("RESTAURANTS_JSON no contiene JSON válido") from exc
    if not isinstance(items, list):
        raise RuntimeError("RESTAURANTS_JSON debe ser una lista")

    restaurants = tuple(
        _restaurant_from_item(item, position) for position, item in enumerate(items, start=1)
    )
    if not restaurants:
        raise RuntimeError("RESTAURANTS_JSON debe contener al menos un restaurante")
    if len({restaurant.id for restaurant in restaurants}) != len(restaurants):
        raise RuntimeError("RESTAURANTS_JSON debe contener IDs únicos")
    if len({restaurant.source_site for restaurant in restaurants}) != len(restaurants):
        raise RuntimeError("RESTAURANTS_JSON debe contener source_site únicos")
    return tuple(sorted(restaurants, key=lambda restaurant: restaurant.display_order))
