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

# The row FSANZ requires on every panel, in the milligrams it is printed in.
SODIUM_LABEL = """
             Per serve  Per 100g
Energy       590kJ      1000kJ
Protein      5.6g       9.5g
Fat, Total   2.0g       3.4g
Carbohydrate 39.2g      39.2g
Sodium       145mg      355mg
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


def test_the_sodium_row_is_read_in_milligrams() -> None:
    panel = parse_panel(SODIUM_LABEL)

    # The per-serve figure is 145: the same column rule as every other row.
    assert panel["sodium"] == 355
    assert_usable_nutrients(panel)


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ("Sodium 355mg", 355),
        # A label writing grams means the same figure a thousand times over.
        ("Sodium 0.4g", 400),
        # No unit at all is the milligrams the label would have printed.
        ("Sodium 355", 355),
    ],
    ids=["milligrams", "grams", "no-unit"],
)
def test_a_sodium_figure_is_stored_in_milligrams_whatever_it_was_written_in(
    row: str, expected: float
) -> None:
    assert parse_panel(row)["sodium"] == expected


def test_a_salt_row_is_not_read_as_sodium() -> None:
    # Salt is 2.5 times its sodium, so reading one as the other overstates it
    # by 150 percent. A panel that prints only salt has no sodium figure.
    assert "sodium" not in parse_panel("Salt 0.9g")


def test_an_ingredient_naming_monosodium_is_not_a_sodium_row() -> None:
    # Pasted text carries more than the panel, and the row this must not read
    # is the one whose name merely contains "sodium".
    text = "Sodium 355mg\nIngredients: water, monosodium glutamate 0.5g"

    assert parse_panel(text)["sodium"] == 355


def test_sodium_beyond_a_hundred_grams_per_hundred_gram_is_refused() -> None:
    salt = {"kcal": 1, "protein": 0, "fat": 0, "carbs": 0, "sodium": 38758}

    # Pure table salt is the ceiling anything edible reaches, and it passes.
    assert_usable_nutrients(salt)

    with pytest.raises(NutritionError, match="sodium"):
        assert_usable_nutrients({**salt, "sodium": 200_000})


def test_a_zero_calorie_panel_may_still_carry_sodium() -> None:
    panel = parse_panel("Energy 0kJ\nProtein 0g\nFat 0g\nSodium 38758mg")

    # Sodium carries no energy, so a figure for it cannot contradict the
    # declaration. Table salt is exactly that shape, and refusing it would
    # leave the one product whose sodium matters most unstorable.
    assert nutrients_for_storage(panel, zero_calorie=True) == {
        "kcal": 0,
        "protein": 0,
        "fat": 0,
        "carbs": 0,
        "sodium": 38758,
    }


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
