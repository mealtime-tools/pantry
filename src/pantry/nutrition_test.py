"""How a written nutrition row is read, row by row."""

import pytest
from mealtime_nutrients import KJ_PER_KCAL

from pantry.nutrition import (
    NutritionError,
    energy_to_kcal,
    panel_from_rows,
)


def test_kilojoules_are_divided_by_the_published_ratio() -> None:
    """4.184 exactly. The old 0.239006 reciprocal was rounded, and wrong."""
    # The ratio is a Decimal; a record still holds floats, so this is where
    # the figure crosses into the lossy domain.
    assert energy_to_kcal(1000, "kJ") == float(1000 / KJ_PER_KCAL)
    assert energy_to_kcal(4184, "kj") == 1000
    assert energy_to_kcal(239, "kcal") == 239


def test_a_kilojoule_row_is_converted_and_not_carried() -> None:
    """The panel leaves the parser in kcal; kJ is not a stored key."""
    panel = panel_from_rows([("Energy", "4184kJ")])

    assert panel == {"kcal": 1000}


def test_an_unmarked_energy_figure_is_read_as_kilojoules() -> None:
    """Every panel this parser sees prints kJ; only a US label omits it."""
    assert panel_from_rows([("Energy", "4184")]) == {"kcal": 1000}


def test_a_dual_unit_energy_row_keeps_the_printed_calories() -> None:
    """The label already did the arithmetic; its own figure beats ours."""
    panel = panel_from_rows([("Energy", "1000kJ (240Cal)")])

    assert panel == {"kcal": 240}


def test_a_fat_sub_row_is_read_as_the_fat_it_names() -> None:
    """Each sub-row before the fat row it would otherwise be counted as."""
    rows = [
        ("Fat, total", "10g"),
        ("- Saturated", "4g"),
        ("- Trans", "0.1g"),
        ("Mono-unsaturated fat", "3g"),
        ("Polyunsaturated Fat", "2g"),
    ]

    assert panel_from_rows(rows) == {
        "fat": 10,
        "saturated_fat": 4,
        "trans_fat": 0.1,
        "monounsaturated_fat": 3,
        "polyunsaturated_fat": 2,
    }


def test_the_generic_fat_row_still_wins_only_what_is_left() -> None:
    """ "Saturated Fat" names the sub-row, not the total it sits under."""
    assert panel_from_rows([("Saturated Fat", "4g")]) == {"saturated_fat": 4}
    assert panel_from_rows([("Total Fat", "10g")]) == {"fat": 10}


def test_unsaturated_fat_is_not_read_as_its_saturated_sub_row() -> None:
    """ "unsaturated" contains "saturated", so the longer name leads."""
    panel = panel_from_rows([("Unsaturated fat", "5g")])

    assert panel == {"unsaturated_fat": 5}


def test_an_ingredient_naming_sodium_reaches_no_row_at_all() -> None:
    """The skip rule still stands between "bicarbonate" and the carbs row."""
    assert panel_from_rows([("Sodium Bicarbonate (500)", "500")]) == {}


def test_salt_is_skipped_rather_than_read_as_its_sodium() -> None:
    """Salt is 2.5 times its sodium; taking one for the other overstates."""
    assert panel_from_rows([("Salt", "1.2g")]) == {}


def test_a_sodium_row_is_still_read_from_its_own_name() -> None:
    assert panel_from_rows([("Sodium", "400mg")]) == {"sodium": 0.4}


def test_a_milligram_row_now_in_the_vocabulary_is_read() -> None:
    """These were discarded by the skip rule until the vocabulary held them."""
    rows = [("Cholesterol", "30mg"), ("Potassium", "400mg")]

    assert panel_from_rows(rows) == {"cholesterol": 0.03, "potassium": 0.4}


@pytest.mark.parametrize("unit", ["µg", "μg", "mcg", "MCG"])
def test_a_microgram_figure_converts_instead_of_becoming_grams(
    unit: str,
) -> None:
    """The bare regex read "1.2µg" as 1.0 with no unit, then refused it."""
    panel = panel_from_rows([("Cholesterol", f"1.2{unit}")])

    assert panel == {"cholesterol": 0.0000012}


def test_a_microgram_unit_stated_in_the_row_name_is_read() -> None:
    """A structured source often puts the unit beside the name instead."""
    assert panel_from_rows([("Cholesterol (µg)", "1.2")]) == {
        "cholesterol": 0.0000012
    }


def test_a_macro_needs_no_unit_and_every_other_nutrient_does() -> None:
    """1000x apart, so a bare trace figure is a guess between two answers."""
    assert panel_from_rows([("Protein", "8.5")]) == {"protein": 8.5}
    assert panel_from_rows([("Total Fat", "10")]) == {"fat": 10}

    with pytest.raises(NutritionError):
        panel_from_rows([("Cholesterol", "30")])
    with pytest.raises(NutritionError):
        panel_from_rows([("- Saturated", "4")])


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (("Calcium", "120mg"), {"calcium": 0.12}),
        (("Iron", "3.2mg"), {"iron": 0.0032}),
        (("Vitamin D", "1.2µg"), {"vitamin_d": 0.0000012}),
        (("Folic Acid", "194µg"), {"folic_acid": 0.000194}),
        (("Pantothenic-Acid", "1.4mg"), {"pantothenic_acid": 0.0014}),
    ],
)
def test_a_vitamin_or_mineral_row_is_read_from_its_wire_name(
    row: tuple[str, str], expected: dict[str, float]
) -> None:
    """Derived from the vocabulary, so an added name is read without an edit."""
    assert panel_from_rows([row]) == expected


def test_a_longer_vitamin_name_is_not_claimed_by_a_shorter_one() -> None:
    """B12 contains no B6, but both contain the stem the other would match."""
    assert panel_from_rows([("Vitamin B12", "2.4mcg")]) == {
        "vitamin_b12": 0.0000024
    }
    assert panel_from_rows([("Vitamin B6", "0.5mg")]) == {"vitamin_b6": 0.0005}


def test_the_derived_rows_leave_the_hand_written_order_alone() -> None:
    """Appended, so no derived name may claim a row the rules above own."""
    assert panel_from_rows([("- Saturated", "0.6g")]) == {"saturated_fat": 0.6}
    assert panel_from_rows([("Fat, Total", "3.6g")]) == {"fat": 3.6}
    assert panel_from_rows([("Sodium Bicarbonate", "(500)")]) == {}
