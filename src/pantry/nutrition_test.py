"""Rules 5, 6 and 11: what a label says, and what is refused."""

import pytest

from pantry.nutrition import (
    NutritionError,
    panel_from_rows,
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
        ("Sodium       145mg     355mg", 0.355),
        # Both spellings of the same figure, stored identically: the unit the
        # label wrote is the only thing that decides, and grams is the target.
        ("Sodium 400mg", 0.4),
        ("Sodium 0.4g", 0.4),
        # No unit at all is grams, exactly as an unmarked protein row is. A
        # sodium-shaped milligram figure would be 355 g per 100 g and the
        # ceiling refuses it, which is the recoverable failure.
        ("Sodium: 355 mg", 0.355),
        # A trace amount is a bound, and the bound is the only figure the
        # label carries -- which is what every other row already does with
        # "LESS THAN 1.0g". Low-sodium packs are where this wording turns up.
        ("Sodium LESS THAN 5mg", 0.005),
        ("Sodium < 355mg", 0.355),
    ],
    ids=[
        "two-column",
        "milligrams",
        "grams",
        "colon",
        "less-than",
        "bound",
    ],
)
def test_a_sodium_row_is_stored_in_the_grams_every_nutrient_uses(
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
    # A row this declines is absent from the record, which is recoverable in a
    # way a wrong figure is not. The whole dict is asserted rather than the
    # sodium key alone: "Sodium Bicarbonate" matches the *carbs* pattern on
    # "bicarbonate", and a previous attempt shipped {"carbs": 471.0} because
    # every test here looked only at .get("sodium").
    assert parse_panel(line) == {}


def test_an_ingredient_list_alone_parses_to_nothing_at_all() -> None:
    line = (
        "Ingredients: Water, Wheat Flour, Sodium Bicarbonate (500), "
        "Emulsifier (471)"
    )

    # Not "no sodium" -- nothing. The additive codes are the trap: 500 and 471
    # would both read as plausible figures for whichever row claimed them.
    assert parse_panel(line) == {}


def test_an_ingredient_list_never_overwrites_the_panel_row() -> None:
    panel = parse_panel(APRICOT_LABEL)

    # The last matching line wins, so a trailing ingredient list is the shape
    # that would silently replace a figure that parsed correctly.
    assert panel["sodium"] == 0.01

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
        "sodium": 38.758,
    }


def test_a_zero_calorie_panel_still_refuses_a_nutrient_with_calories() -> None:
    panel = parse_panel("Energy 0kJ\nProtein 0g\nSugars 27.2g")

    # Three real Coles rows are this shape -- zero energy, zero macros, sugar
    # printed -- and they are half-parsed panels rather than food.
    with pytest.raises(NutritionError, match="--zero-calorie conflicts"):
        nutrients_for_storage(panel, zero_calorie=True)


def test_an_impossible_sodium_is_refused_on_the_zero_calorie_path(
    make_deps, run, store_path
) -> None:
    """The declaration exempts a mineral from the zero check, not the rules.

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
        stdin="Energy 0kJ\nSodium 500g",
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


@pytest.mark.parametrize(
    "line",
    ["Sodium 355", "Dietary Fibre 4.1", "Sugars 2.2"],
    ids=["sodium", "fiber", "sugar"],
)
def test_a_nutrient_figure_without_a_unit_is_refused(line: str) -> None:
    """1000x apart, so a bare figure is a guess between two answers.

    A macro is only printed in grams, so it needs no unit; every nutrient
    that can be printed in milligrams does.
    """
    with pytest.raises(NutritionError, match="with no unit"):
        parse_panel(line)


def test_a_macro_needs_no_unit() -> None:
    assert parse_panel("Protein 8.5\nFat 3.6") == {"protein": 8.5, "fat": 3.6}


COLES_ROWS = [
    ("Energy", "980kJ"),
    ("Protein", "8.5g"),
    ("Fat, Total", "3.6g"),
    ("- Saturated", "0.6g"),
    ("Carbohydrate", "38.4g"),
    ("- Sugars", "2.2g"),
    ("Dietary Fibre", "4.1g"),
    ("Sodium", "400mg"),
]


def test_structured_rows_read_a_whole_panel() -> None:
    assert panel_from_rows(COLES_ROWS) == {
        "kcal": 234.22588,
        "kj": 980.0,
        "protein": 8.5,
        "fat": 3.6,
        "carbs": 38.4,
        "sugar": 2.2,
        "fiber": 4.1,
        "sodium": 0.4,
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [("Sodium", "400mg"), ("Sodium (mg)", "400"), ("Sodium mg", "400")],
    ids=["unit-on-figure", "unit-in-name", "bare-unit-in-name"],
)
def test_a_structured_row_takes_its_unit_from_wherever_it_is_stated(
    name: str, value: str
) -> None:
    """The unit is information the source handed over; using it beats guessing.

    A pasted label can only put the unit beside the figure. A structured row
    can put it in either place, and "Sodium (g) 0.4" read as milligrams is
    wrong by a thousand.
    """
    assert panel_from_rows([(name, value)]) == {"sodium": 0.4}
    assert panel_from_rows([("Sodium (g)", "0.4")]) == {"sodium": 0.4}


def test_a_structured_row_with_no_unit_anywhere_is_refused() -> None:
    with pytest.raises(NutritionError, match="with no unit"):
        panel_from_rows([("Sodium", "400")])


@pytest.mark.parametrize(
    "name",
    ["Sodium Bicarbonate", "Ingredients", "Salt", "Sodium (as salt)"],
    ids=["additive", "ingredient-list", "salt", "salt-restated"],
)
def test_a_structured_row_that_names_no_nutrient_is_not_read(
    name: str,
) -> None:
    """Nothing here has to be told apart from prose: the source named it."""
    assert panel_from_rows([(name, "500")]) == {}
