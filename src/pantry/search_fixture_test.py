"""The twenty ingredients a recipe names, and what each one must resolve to.

Asserted on the kind of food rather than on a record id, because ranking is a
judgement call in a hundred small places and the ids will churn: the words the
name must carry, the words that would mean a different food, and one macro
bounded widely enough to admit a better record. `Oil, olive` passes whichever
row supplies it; `Olive Oil Rusk` fails on the word and on the fat alike.

Read against the shipped shards, never the user's store, so the answer is the
same on every machine.
"""

from decimal import Decimal

import pytest

from pantry.data import data_dir, read_shards
from pantry.local import Local

# query, words the name must carry, words that would mean another food,
# and the macro that tells this food from its near misses.
FIXTURE = (
    ("olive oil", ("oil", "olive"), ("rusk", "tuna"), "fat", 80, 100),
    ("brown onion", ("onion",), ("gravy", "soup"), "kcal", 15, 60),
    ("garlic", ("garlic",), ("fried", "bread", "butter"), "kcal", 90, 160),
    ("chicken breast", ("chicken", "breast"), (), "protein", 18, 30),
    ("basmati rice", ("basmati", "rice"), (), "carbs", 15, 85),
    ("greek yoghurt", ("greek",), ("flavoured",), "protein", 3, 12),
    ("cheddar cheese", ("cheddar",), ("slices", "dip"), "protein", 18, 30),
    ("baby spinach", ("spinach",), (), "kcal", 5, 45),
    ("cherry tomatoes", ("tomato",), ("sauce", "paste"), "kcal", 10, 45),
    ("red capsicum", ("capsicum", "red"), ("fried", "dip"), "kcal", 10, 45),
    ("chickpeas", ("chickpea",), ("pasta", "dip"), "protein", 5, 25),
    ("tahini", ("tahini",), (), "fat", 40, 70),
    ("lemon", ("lemon",), ("juice", "cordial"), "kcal", 10, 45),
    ("cumin", ("cumin",), ("sauce", "seasoning"), "protein", 10, 25),
    ("paprika", ("paprika",), (), "protein", 8, 20),
    ("rolled oats", ("oats", "rolled"), (), "protein", 8, 18),
    ("milk", ("milk",), ("evaporated", "condensed"), "kcal", 30, 100),
    ("eggs", ("egg",), ("easter", "noodle"), "protein", 9, 16),
    ("butter", ("butter",), ("peanut", "cashew", "almond"), "fat", 70, 90),
    ("plain flour", ("flour", "plain"), ("gluten",), "protein", 7, 15),
)


@pytest.fixture(scope="module")
def shipped() -> Local:
    """The shards as installed, read once for the whole fixture."""
    return Local(read_shards(data_dir({})))


@pytest.mark.parametrize("query,wants,rejects,macro,low,high", FIXTURE)
def test_an_ingredient_resolves_to_the_right_kind_of_food(
    shipped: Local,
    query: str,
    wants: tuple[str, ...],
    rejects: tuple[str, ...],
    macro: str,
    low: int,
    high: int,
) -> None:
    found = shipped.search(query, limit=1)
    assert found, f"{query} resolved to nothing"

    best = found[0]
    name = best["name"].lower()
    assert all(word in name for word in wants), f"{query} -> {best['name']}"
    assert not [w for w in rejects if w in name], f"{query} -> {best['name']}"

    value = best.get(macro)
    assert value is not None, f"{query} -> {best['name']} states no {macro}"
    assert Decimal(low) <= Decimal(value) <= Decimal(high), (
        f"{query} -> {best['name']} has {macro} {value}"
    )
