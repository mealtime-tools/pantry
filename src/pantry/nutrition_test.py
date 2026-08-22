"""Rules 5, 6 and 11: what a label says, and what is refused."""

import pytest

from pantry.nutrition import (
    _SODIUM_ROW,
    NutritionError,
    assert_usable_nutrients,
    assert_usable_sodium,
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


# A real pack: the panel, then the ingredient list underneath it.
APRICOT_LABEL = """
             Per serve  Per 100g
Energy       234kJ      1090kJ
Protein      0.8g       3.4g
Fat, Total   0.1g       0.5g
Carbohydrate 12.4g      57.8g
Sodium       2mg        10mg
Ingredients: Dried Apricots (99%), Preservative (Sodium Metabisulphite 223)
"""


@pytest.mark.parametrize(
    "line",
    [
        "Ingredients: Water, Sodium Bicarbonate (500), Emulsifier (471)",
        "Ingredients: Pork (85%), Sodium Nitrite (250)",
        "Contains Sodium Metabisulphite (223) 0.5g",
        "Low sodium - 30% less than our regular recipe",
        "Ingredients: Flavour Enhancer (monosodium glutamate 0.5g)",
        # Rejected by the head anchor alone: the figure sits right beside the
        # word, so nothing else in the pattern is standing in the way.
        "Ingredients: Water, Flour, sodium 500",
        "Contains sodium: 500mg per serve",
        "Preservative (sodium 250)",
        # Rejected by the closed set of label words alone: no parenthesis
        # separates the additive name from its code.
        "Sodium Bicarbonate 500",
        "Sodium Metabisulphite 223",
        "Sodium Nitrite 250",
        # Rejected by the closed set of separators alone: a word may not
        # precede one of the label words either.
        "Sodium Bicarbonate mg 500",
        # Both guards at once, and the two rows that carry a salt figure
        # rather than a sodium one.
        "Sodium Bicarbonate (500)",
        "| Sodium Bicarbonate | 500 |",
        "Sodium (as salt) 1.0g",
        "Sodium/Salt 0.9g",
    ],
    ids=[
        "bicarbonate",
        "nitrite",
        "metabisulphite",
        "marketing-claim",
        "monosodium",
        "lowercase-in-ingredients",
        "lowercase-after-contains",
        "lowercase-in-parentheses",
        "bicarbonate-unparenthesized",
        "metabisulphite-unparenthesized",
        "nitrite-unparenthesized",
        "word-before-a-label-word",
        "additive-at-line-head",
        "additive-in-a-table-row",
        "salt-figure-in-brackets",
        "salt-figure-after-a-slash",
    ],
)
def test_only_the_panel_row_is_read_as_sodium(line: str) -> None:
    # Every additive code -- 211, 223, 250, 450, 500, 621 -- sits inside
    # sodium's plausible milligram range, so a figure taken off an ingredient
    # list passes every later check. Sugar is protected from the same class of
    # bug by the 100 g ceiling; sodium has no such luck.
    assert "sodium" not in parse_panel(line)


def test_an_ingredient_list_never_overwrites_the_panel_row() -> None:
    # The last matching line wins, so a trailing ingredient list is the shape
    # that silently replaces a figure that parsed correctly.
    assert parse_panel(APRICOT_LABEL)["sodium"] == 10


@pytest.mark.parametrize(
    "row",
    [
        "Sodium 355mg",
        "  Sodium      145mg     355mg",
        "Sodium (mg) 355",
        "Sodium, Na 355mg",
        "Sodium: 355 mg",
        # `Fat, Total` is how the retailer rows really read, and
        # `_rows_to_panel` renders a name and its value into one line, so the
        # sibling wording arrives in exactly this shape.
        "Sodium, total 355mg",
        "Sodium Total 355mg",
        "Sodium (total) 355mg",
        # A pasted markdown table and a dashed row: the shapes an agent
        # actually hands to `add --manual`.
        "| Sodium | 355mg |",
        "- Sodium 355mg",
        "• Sodium 355mg",
        "* Sodium 355mg",
        "> Sodium 355mg",
        # Two label words in one row, which is what makes the repetition in
        # the pattern do any work.
        "Sodium, total (mg) 355",
        "Sodium, total, mg, 355",
    ],
    ids=[
        "plain",
        "indented",
        "unit-in-label",
        "qualified",
        "colon",
        "total-after-comma",
        "total-as-a-word",
        "total-in-brackets",
        "markdown-table-row",
        "dashed-row",
        "bulleted-row",
        "starred-row",
        "quoted-row",
        "total-then-unit",
        "total-then-unit-comma-separated",
    ],
)
def test_a_panel_row_is_read_however_the_label_writes_it(row: str) -> None:
    assert parse_panel(row)["sodium"] == 355


def test_a_trace_sodium_row_stores_the_bound_the_label_printed() -> None:
    # A trace amount is written as a bound and the bound is the only figure
    # the label carries, which is what every other row already does with
    # "LESS THAN 1.0g". Low-sodium packs are where this wording turns up.
    assert parse_panel("Sodium LESS THAN 5mg")["sodium"] == 5
    assert parse_panel("Sodium less than 5 mg")["sodium"] == 5
    assert parse_panel("Sodium < 5mg")["sodium"] == 5


@pytest.mark.parametrize(
    "row", ["Sodium (g) 0.4", "Sodium g 0.4"], ids=["bracketed", "bare"]
)
def test_a_row_whose_unit_is_beside_its_name_is_declined(row: str) -> None:
    # `_read_sodium` can only see the unit attached to the figure, so reading
    # this row would store 0.4 mg where 400 was printed -- a plausible-looking
    # number, wrong by a thousand, that no later check can catch. Declined
    # instead: absent means unknown, and unknown is recoverable.
    assert "sodium" not in parse_panel(row)

    # The same figure with its unit on the number is still read.
    assert parse_panel("Sodium 0.4g")["sodium"] == 400


def test_the_sodium_row_pattern_never_reaches_across_a_line() -> None:
    # Reaching for the pattern itself, because the property belongs to it and
    # not to `parse_panel`, which only ever hands it one line. A later caller
    # that ran it over a whole label would otherwise read the next row's
    # number as this row's figure.
    assert _SODIUM_ROW.search("Sodium\n355mg") is None
    assert _SODIUM_ROW.search("Sodium less\nthan 5mg") is None


def test_a_salt_row_is_not_read_as_sodium() -> None:
    # Salt is 2.5 times its sodium, so reading one as the other overstates it
    # by 150 percent. A panel that prints only salt has no sodium figure.
    assert "sodium" not in parse_panel("Salt 0.9g")


def test_sodium_beyond_a_hundred_grams_per_hundred_gram_is_refused() -> None:
    salt = {"kcal": 1, "protein": 0, "fat": 0, "carbs": 0, "sodium": 38758}

    # Pure table salt is the ceiling anything edible reaches, and it passes.
    assert_usable_nutrients(salt)

    with pytest.raises(NutritionError, match="sodium"):
        assert_usable_nutrients({**salt, "sodium": 200_000})


@pytest.mark.parametrize(
    "sodium",
    [-1, -0.0001, float("nan"), float("inf"), float("-inf"), 100_001],
    ids=["negative", "barely-negative", "nan", "inf", "-inf", "over-ceiling"],
)
def test_an_impossible_sodium_figure_is_refused(sodium: float) -> None:
    with pytest.raises(NutritionError, match="sodium"):
        assert_usable_sodium({"sodium": sodium})


@pytest.mark.parametrize(
    "sodium",
    [0, 38758, 100_000, None],
    ids=["printed-zero", "table-salt", "ceiling", "absent"],
)
def test_a_possible_sodium_figure_is_accepted(sodium: float | None) -> None:
    # The ceiling is inclusive, matching `_check_mass`, and an absent figure
    # is not an error: this is the check for the paths that carry sodium and
    # nothing else.
    assert_usable_sodium({"sodium": sodium})


def test_a_zero_calorie_panel_has_its_sodium_checked() -> None:
    panel = parse_panel("Energy 0kJ\nProtein 0g\nSodium 500000mg")

    # This path returns before the full panel rules run, and it is the only
    # path a sodium figure survives, so the ceiling has to be applied here.
    with pytest.raises(NutritionError, match="sodium"):
        nutrients_for_storage(panel, zero_calorie=True)


def test_a_zero_calorie_panel_may_still_carry_sodium() -> None:
    panel = parse_panel("Energy 0kJ\nProtein 0g\nFat 0g\nSodium 38758mg")

    # Sodium carries no energy, so a figure for it cannot contradict the
    # declaration. Table salt is exactly that shape, and refusing it would
    # mean a zero-energy product could only be added by discarding its
    # sodium.
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
