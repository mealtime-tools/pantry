"""What Open Food Facts is asked for a barcode, and what comes back."""

import json
from decimal import Decimal

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


def client(body: str, seen: list[str] | None = None):
    def get(url: str) -> str:
        if seen is not None:
            seen.append(url)
        return body

    return OpenFoodFacts(get=get)


def test_a_barcode_is_read_from_the_product_endpoint() -> None:
    """The search index answers `code:` with a name and no nutriments."""
    seen: list[str] = []

    reader = client(json.dumps(PRODUCT), seen)

    found = reader.product("8852511011448")

    assert found is not None
    assert found["kcal"] == Decimal("724.98")
    assert seen == [
        "https://world.openfoodfacts.org/api/v2/product/8852511011448.json"
    ]


def test_a_code_the_database_lacks_is_absent_not_invented() -> None:
    assert client(json.dumps({"status": 0})).product("1") is None


def test_every_read_asks_the_source() -> None:
    """There was a 24-hour cache here, and it held parsed records. That made
    `add --refresh` re-read the cache instead of the source, and kept a fix
    to the parser invisible for a day. `add` checks the store first, so it
    saved almost nothing."""
    seen: list[str] = []
    reader = client(json.dumps(PRODUCT), seen)

    reader.product("8852511011448")
    reader.product("8852511011448")

    assert len(seen) == 2


def test_an_unreadable_answer_is_refused_rather_than_parsed() -> None:
    with pytest.raises(RemoteFailure):
        client("not json").product("8852511011448")


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


def test_energy_stated_only_in_kilojoules_is_still_energy() -> None:
    """Dropping it left a panel with macros and no calories at all."""
    found = client(json.dumps(KILOJOULES_ONLY)).product("9310645106380")

    assert found is not None
    assert found["kcal"] == Decimal("492.351816")


def test_a_stated_calorie_figure_beats_converting_the_kilojoules() -> None:
    """Both present: the source's own number, not our arithmetic."""
    both = {"status": 1, "product": {**KILOJOULES_ONLY["product"]}}
    both["product"]["nutriments"] = {
        "energy-kj_100g": 2060,
        "energy-kcal_100g": 490,
    }

    found = client(json.dumps(both)).product("9310645106380")

    assert found is not None
    assert found["kcal"] == Decimal("490")
