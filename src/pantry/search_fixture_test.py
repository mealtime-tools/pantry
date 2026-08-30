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

from pantry.data import SHIPPED_SOURCES, data_dir, read_shard
from pantry.local import Local

# query, words the name must carry, words that would mean another food,
# and the macro that tells this food from its near misses.
FIXTURE = (
    ("olive oil", ("oil", "olive"), ("rusk", "tuna"), "fat", 80, 100),
    ("brown onion", ("onion",), ("gravy", "soup"), "kcal", 15, 60),
    ("garlic", ("garlic",), ("fried", "bread", "butter"), "kcal", 90, 160),
    ("chicken breast", ("chicken", "breast"), (), "protein", 18, 30),
    # Shipped data names no variety, so the assertion is the panel this
    # must reach: an uncooked white rice, not the brown that sorted first.
    (
        "basmati rice",
        ("rice", "white"),
        ("brown", "wild", "boiled"),
        "carbs",
        15,
        85,
    ),
    # No greek yoghurt ships either. What must not happen is a flavoured
    # one outranking the plain, which is a different food.
    (
        "greek yoghurt",
        ("yoghurt", "natural"),
        ("flavoured",),
        "protein",
        3,
        12,
    ),
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
    (
        "eggs",
        ("egg",),
        ("easter", "noodle", "white", "yolk"),
        "protein",
        9,
        16,
    ),
    ("butter", ("butter",), ("peanut", "cashew", "almond"), "fat", 70, 90),
    ("plain flour", ("flour", "plain"), ("gluten",), "protein", 7, 15),
)

COMMON_WHOLE_FOODS = (
    "almonds",
    "apples",
    "avocados",
    "bananas",
    "broccoli",
    "brown rice",
    "carrots",
    "celery",
    "chickpeas",
    "chicken breast",
    "cucumbers",
    "eggs",
    "garlic",
    "ginger",
    "green beans",
    "lentils",
    "lemons",
    "milk",
    "mushrooms",
    "rolled oats",
    "olive oil",
    "onions",
    "oranges",
    "peanuts",
    "pears",
    "potatoes",
    "pumpkin",
    "quinoa",
    "red capsicum",
    "salmon",
    "spinach",
    "strawberries",
    "sweet potatoes",
    "tofu",
    "tomatoes",
    "tuna",
    "walnuts",
    "beef mince",
    "pork",
    "lamb",
    "corn",
    "peas",
    "cabbage",
    "cauliflower",
    "zucchini",
    "cashews",
    "coconut",
    "blueberries",
    "pineapple",
    "watermelon",
)


@pytest.fixture(scope="module")
def shipped() -> Local:
    """Only what a user who installs this package actually gets.

    Reading the whole data directory made this pass on a maintainer's machine
    for the wrong reason: `data/coles.jsonl` is local-only and git-ignored, and
    two of these queries were being answered by rows nobody else has.
    """
    rows = [
        row
        for source in SHIPPED_SOURCES
        for row in read_shard(data_dir({}) / f"{source}.jsonl", source)
    ]
    return Local(rows)


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


@pytest.mark.parametrize("query", COMMON_WHOLE_FOODS)
def test_a_common_whole_food_resolves_to_a_composition_record(
    shipped: Local, query: str
) -> None:
    found = shipped.search(query, limit=1)
    assert found, f"{query} resolved to nothing"

    best = found[0]
    assert best["match"]["tier"] == "composition", (
        f"{query} -> {best['source']}:{best['name']}"
    )
    assert best["match"]["score"] >= Decimal("0.7"), (
        f"{query} -> {best['name']} is a weak match"
    )
