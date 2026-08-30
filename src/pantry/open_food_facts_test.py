"""What Open Food Facts is asked for a barcode, and what comes back."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from pantry.open_food_facts import OpenFoodFacts, RemoteFailure

# Shaped like the product endpoint's answer, carrying every field a record
# is built from. The live row for this code states only energy, which is why
# the macros here are invented rather than copied.
PRODUCT = {
    "status": 1,
    "product": {
        "code": "8852511011448",
        "product_name": "MAYONNAISE",
        "brands": "Kewpie",
        "nutriments": {
            "energy-kcal_100g": 724.98,
            "fat_100g": 80,
            "carbohydrates_100g": 1,
            "proteins_100g": 1,
        },
    },
}


def client(tmp_path: Path, body: str, seen: list[str] | None = None):
    def get(url: str) -> str:
        if seen is not None:
            seen.append(url)
        return body

    return OpenFoodFacts(tmp_path, get=get)


def test_a_barcode_is_read_from_the_product_endpoint(tmp_path: Path) -> None:
    """The search index answers `code:` with a name and no nutriments."""
    seen: list[str] = []

    reader = client(tmp_path, json.dumps(PRODUCT), seen)

    found = reader.product("8852511011448")

    assert found is not None
    assert found["kcal"] == Decimal("724.98")
    assert seen == [
        "https://world.openfoodfacts.org/api/v2/product/8852511011448.json"
    ]


def test_a_code_the_database_lacks_is_absent_not_invented(
    tmp_path: Path,
) -> None:
    assert client(tmp_path, json.dumps({"status": 0})).product("1") is None


def test_a_barcode_is_fetched_once_and_then_reused(tmp_path: Path) -> None:
    seen: list[str] = []
    reader = client(tmp_path, json.dumps(PRODUCT), seen)

    reader.product("8852511011448")
    reader.product("8852511011448")

    assert len(seen) == 1


def test_an_unreadable_answer_is_refused_rather_than_parsed(
    tmp_path: Path,
) -> None:
    with pytest.raises(RemoteFailure):
        client(tmp_path, "not json").product("8852511011448")


# What Open Food Facts holds for Coles Grated Parmesan, 9310645106380: energy
# stated only in kilojoules. Verified live 2026-08-30.
KILOJOULES_ONLY = {
    "status": 1,
    "product": {
        "code": "9310645106380",
        "product_name": "Grated Parmesan",
        "brands": "Coles",
        "nutriments": {
            "energy-kj_100g": 2060,
            "proteins_100g": 33.2,
            "fat_100g": 39.4,
        },
    },
}


def test_energy_stated_only_in_kilojoules_is_still_energy(
    tmp_path: Path,
) -> None:
    """Dropping it left a panel with macros and no calories at all."""
    found = client(tmp_path, json.dumps(KILOJOULES_ONLY)).product(
        "9310645106380"
    )

    assert found is not None
    assert found["kcal"] == Decimal("492.351816")


def test_a_stated_calorie_figure_beats_converting_the_kilojoules(
    tmp_path: Path,
) -> None:
    """Both present: the source's own number, not our arithmetic."""
    both = {"status": 1, "product": {**KILOJOULES_ONLY["product"]}}
    both["product"]["nutriments"] = {
        "energy-kj_100g": 2060,
        "energy-kcal_100g": 490,
    }

    found = client(tmp_path, json.dumps(both)).product("9310645106380")

    assert found is not None
    assert found["kcal"] == Decimal("490")
