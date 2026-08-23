import json

import pytest

from restaurant_live_ops.restaurants import restaurants_from_env


def valid_restaurant(**overrides: object) -> dict[str, object]:
    restaurant: dict[str, object] = {
        "id": "R001",
        "name": "Central",
        "source_site": "Central card",
        "display_order": 1,
        "has_drive_through": True,
        "workforce_expected_hours": [8, 9],
    }
    restaurant.update(overrides)
    return restaurant


def test_restaurants_are_loaded_from_neutral_environment_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "RESTAURANTS_JSON",
        json.dumps(
            [
                {
                    "id": "R002",
                    "name": "North",
                    "source_site": "North card",
                    "display_order": 2,
                    "has_drive_through": False,
                    "workforce_expected_hours": [10, 11],
                },
                {
                    "id": "R001",
                    "name": "Central",
                    "source_site": "Central card",
                    "display_order": 1,
                    "has_drive_through": True,
                    "workforce_expected_hours": [8, 9],
                },
            ]
        ),
    )

    restaurants = restaurants_from_env()

    assert [restaurant.id for restaurant in restaurants] == ["R001", "R002"]
    assert restaurants[0].source_site == "Central card"
    assert restaurants[0].has_drive_through is True
    assert restaurants[0].workforce_expected_hours == (8, 9)


def test_restaurants_are_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESTAURANTS_JSON", raising=False)

    with pytest.raises(RuntimeError, match="RESTAURANTS_JSON"):
        restaurants_from_env()


def test_restaurants_reject_a_non_list_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESTAURANTS_JSON", json.dumps({"restaurants": []}))

    with pytest.raises(RuntimeError, match="debe ser una lista"):
        restaurants_from_env()


def test_restaurants_reject_a_non_object_item(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESTAURANTS_JSON", json.dumps(["R001"]))

    with pytest.raises(RuntimeError, match="elemento 1 debe ser un objeto"):
        restaurants_from_env()


def test_restaurants_reject_a_missing_required_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restaurant = valid_restaurant()
    del restaurant["id"]
    monkeypatch.setenv("RESTAURANTS_JSON", json.dumps([restaurant]))

    with pytest.raises(RuntimeError, match="elemento 1: id debe ser texto no vacío"):
        restaurants_from_env()


def test_restaurants_reject_an_empty_required_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESTAURANTS_JSON", json.dumps([valid_restaurant(name="  ")]))

    with pytest.raises(RuntimeError, match="elemento 1: name debe ser texto no vacío"):
        restaurants_from_env()


def test_restaurants_reject_a_non_string_required_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESTAURANTS_JSON", json.dumps([valid_restaurant(source_site=123)]))

    with pytest.raises(RuntimeError, match="elemento 1: source_site debe ser texto no vacío"):
        restaurants_from_env()


def test_restaurants_reject_a_non_boolean_drive_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "RESTAURANTS_JSON",
        json.dumps([valid_restaurant(has_drive_through="false")]),
    )

    with pytest.raises(RuntimeError, match="has_drive_through debe ser booleano"):
        restaurants_from_env()


@pytest.mark.parametrize(
    "invalid_hours",
    [None, [], [8, 8], [8, 24], [8, True], "8,9"],
)
def test_restaurants_require_unique_nonempty_workforce_expected_hours(
    monkeypatch: pytest.MonkeyPatch,
    invalid_hours: object,
) -> None:
    restaurant = valid_restaurant()
    if invalid_hours is None:
        del restaurant["workforce_expected_hours"]
    else:
        restaurant["workforce_expected_hours"] = invalid_hours
    monkeypatch.setenv("RESTAURANTS_JSON", json.dumps([restaurant]))

    with pytest.raises(RuntimeError, match="workforce_expected_hours"):
        restaurants_from_env()


@pytest.mark.parametrize("invalid_order", [True, "1", 1.5])
def test_restaurants_reject_a_non_integer_display_order(
    monkeypatch: pytest.MonkeyPatch,
    invalid_order: object,
) -> None:
    monkeypatch.setenv(
        "RESTAURANTS_JSON",
        json.dumps([valid_restaurant(display_order=invalid_order)]),
    )

    with pytest.raises(RuntimeError, match="display_order debe ser un entero"):
        restaurants_from_env()


def test_restaurants_reject_duplicate_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "RESTAURANTS_JSON",
        json.dumps([valid_restaurant(), valid_restaurant(source_site="North card")]),
    )

    with pytest.raises(RuntimeError, match="IDs únicos"):
        restaurants_from_env()


def test_restaurants_reject_duplicate_source_sites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "RESTAURANTS_JSON",
        json.dumps([valid_restaurant(), valid_restaurant(id="R002")]),
    )

    with pytest.raises(RuntimeError, match="source_site únicos"):
        restaurants_from_env()
