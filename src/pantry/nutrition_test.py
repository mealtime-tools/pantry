"""Rules 5, 6 and 11: what a label says, and what is refused."""

import pytest

from pantry.nutrition import (
    NutritionError,
    assert_usable_nutrients,
    nutrients_for_storage,
    parse_amount,
    parse_panel,
)

SERVING_FIRST = """
             Per serve  Per 100g
Energy       590kJ      1000kJ
Protein      5.6g       9.5g
Fat, Total   2.0g       3.4g
- Saturated  0.3g       0.5g
Carbohydrate 23.1g      39.2g
- Sugars     1.1g       1.9g
"""

HUNDRED_FIRST = """
             Per 100g   Per serve
Energy       1000kJ     590kJ
Protein      9.5g       5.6g
Fat, Total   3.4g       2.0g
Carbohydrate 39.2g      23.1g
"""


@pytest.mark.parametrize(
    "label",
    [SERVING_FIRST, HUNDRED_FIRST],
    ids=["serving-column-first", "hundred-column-first"],
)
def test_per_hundred_gram_column_wins(label: str) -> None:
    panel = parse_panel(label)

    # The per-serve figures are 5.6 / 2.0 / 23.1; reading those would
    # under-count every recipe using the product by about 60 percent.
    assert panel["protein"] == 9.5
    assert panel["fat"] == 3.4
    assert panel["carbs"] == 39.2

    # Kilojoules are kept as printed, and calories derived rather than guessed.
    assert panel["kj"] == 1000
    assert round(panel["kcal"], 1) == 239.0


@pytest.mark.parametrize(
    "label",
    [
        "Protein 9.5g\nFat, Total 3.4g\nCarbohydrate 39.2g",
        "Energy 1000kJ\nFat, Total 3.4g\nCarbohydrate 39.2g",
        "Energy 1000kJ\nProtein 9.5g\nFat 3.4g\nCarbohydrate 900g",
    ],
    ids=["no-energy", "no-protein", "impossible-carbs"],
)
def test_malformed_panel_is_refused_not_zeroed(label: str) -> None:
    panel = parse_panel(label)

    with pytest.raises(NutritionError):
        assert_usable_nutrients(panel)

    # And the refusal is not something a caller can convert into zeros by
    # asking again without the panel.
    with pytest.raises(NutritionError):
        nutrients_for_storage(panel)


def test_zero_calorie_conflicts_with_any_non_zero_value() -> None:
    panel = parse_panel("Energy 0kJ\nProtein 0g\nFat 0g\nCarbohydrate 0.4g")

    with pytest.raises(NutritionError, match="--zero-calorie conflicts"):
        nutrients_for_storage(panel, zero_calorie=True)

    # An absent panel is the one thing the declaration may fill.
    assert nutrients_for_storage({}, zero_calorie=True) == {
        "kcal": 0,
        "protein": 0,
        "fat": 0,
        "carbs": 0,
    }


# A real pack: the panel, then the ingredient list underneath it.
APRICOT_LABEL = """
             Per serve  Per 100g
Energy       234kJ      1090kJ
Protein      0.8g       3.4g
Fat, Total   0.1g       0.5g
Carbohydrate 12.4g      57.8g
Sodium       2mg        10mg
Ingredients: Dried Apricots (99%), Sodium Bicarbonate (500)
"""


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ("Sodium       145mg     355mg", 355),
        # A label writing grams means the same figure a thousand times over.
        ("Sodium 0.4g", 400),
        # No unit at all is the milligrams the label would have printed.
        ("Sodium 355", 355),
        ("Sodium: 355 mg", 355),
        # A trace amount is a bound, and the bound is the only figure the
        # label carries -- which is what every other row already does with
        # "LESS THAN 1.0g". Low-sodium packs are where this wording turns up.
        ("Sodium LESS THAN 355mg", 355),
        ("Sodium < 355mg", 355),
    ],
    ids=["two-column", "grams", "no-unit", "colon", "less-than", "bound"],
)
def test_a_sodium_row_is_stored_in_the_milligrams_its_label_prints(
    row: str, expected: float
) -> None:
    assert parse_panel(row)["sodium"] == expected


@pytest.mark.parametrize(
    "line",
    [
        "Sodium Bicarbonate (500)",
        "Sodium Nitrite (250)",
        "Sodium Metabisulphite 223",
        "Ingredients: Water, Sodium Bicarbonate (500), Emulsifier (471)",
        "Ingredients: Pork (85%), Sodium Nitrite (250)",
        "Ingredients: Flavour Enhancer (monosodium glutamate 0.5g)",
        "Low sodium - 30% less than our regular recipe",
        "Contains sodium: 500mg per serve",
        # Salt is 2.5 times its sodium, so reading one as the other would
        # overstate the figure by 150 percent.
        "Salt 0.9g",
        "Sodium/Salt 0.9g",
        # Only a unit written on the figure can be converted, so reading this
        # would store 0.4 mg where 400 was printed: a plausible number, wrong
        # by a thousand, that no later check can catch.
        "Sodium (g) 0.4",
    ],
    ids=[
        "bicarbonate",
        "nitrite",
        "metabisulphite",
        "bicarbonate-in-ingredients",
        "nitrite-in-ingredients",
        "monosodium",
        "marketing-claim",
        "prose",
        "salt-row",
        "salt-figure",
        "unit-beside-the-name",
    ],
)
def test_only_the_panel_row_is_read_as_sodium(line: str) -> None:
    # Every additive code -- 211, 223, 250, 450, 500, 621 -- sits inside
    # sodium's plausible milligram range, so a figure taken off an ingredient
    # list passes every later check. Sugar is protected from the same class of
    # bug by the 100 g ceiling; sodium has no such luck. A row this declines
    # is absent from the record, which is recoverable in a way a wrong figure
    # is not.
    assert "sodium" not in parse_panel(line)


def test_an_ingredient_list_never_overwrites_the_panel_row() -> None:
    panel = parse_panel(APRICOT_LABEL)

    # The last matching line wins, so a trailing ingredient list is the shape
    # that would silently replace a figure that parsed correctly.
    assert panel["sodium"] == 10

    # And a line naming sodium is still skipped whole, which is what keeps
    # "Sodium Bicarbonate" out of the carbs row it matches on "bicarbonate".
    assert panel["carbs"] == 57.8


def test_a_zero_calorie_panel_may_still_carry_sodium() -> None:
    panel = parse_panel("Energy 0kJ\nProtein 0g\nFat 0g\nSodium 38758mg")

    # Sodium carries no energy, so a figure for it contradicts nothing. Table
    # salt is exactly that shape, and refusing it would mean a zero-energy
    # product could only be added by discarding its sodium.
    assert nutrients_for_storage(panel, zero_calorie=True) == {
        "kcal": 0,
        "protein": 0,
        "fat": 0,
        "carbs": 0,
        "sodium": 38758,
    }


def test_an_impossible_sodium_is_refused_on_the_zero_calorie_path(
    make_deps, run, store_path
) -> None:
    """The declaration exempts sodium from the zero check, not from the rules.

    A zero-energy panel returns before the panel rules run, so the ceiling
    that refuses more than 100 g of anything per 100 g is applied to the
    record every one of these panels becomes.
    """
    refused = run(
        make_deps(),
        "add",
        "--manual",
        "--zero-calorie",
        "--id",
        "salt",
        "--name",
        "Salt",
        stdin="Energy 0kJ\nSodium 500000mg",
    )

    assert refused.exit_code == 1
    assert "sodium" in refused.stderr
    assert not (store_path / "manual.jsonl").exists()


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("450g", (450.0, "g")),
        ("650 ml", (650.0, "ml")),
        ("59.0 G", (59.0, "g")),
        # An unreadable pack size is absent, not a number without a unit.
        ("4 * 125 g (500 g)", (None, None)),
        ("6 pack", (None, None)),
        (None, (None, None)),
    ],
)
def test_an_amount_needs_both_a_number_and_a_unit(written, expected) -> None:
    assert parse_amount(written) == expected
