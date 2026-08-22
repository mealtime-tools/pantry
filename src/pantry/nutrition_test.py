"""What pantry still decides about a panel, now that it does not read one."""

import pytest

from pantry.nutrition import (
    NutritionError,
    assert_usable_nutrients,
    nutrients_for_storage,
    parse_amount,
    reconciliation_note,
)

LOAF = {"kcal": 234.23, "protein": 8.5, "fat": 3.6, "carbohydrates": 38.4}

# A real shape: the energy of a fried snack against the macros of a plain one,
# which is what two columns read from two different places produces. Every
# figure is plausible alone and the macros are only 90 g per 100 g, so no
# ceiling here can see it.
MISMATCHED = {
    "kcal": 707.46,
    "protein": 5.1,
    "fat": 20.3,
    "carbohydrates": 64.3,
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
    """The one written figure left in this module, and it is packaging."""
    assert parse_amount(written) == expected


def test_a_panel_that_adds_up_is_stored() -> None:
    assert_usable_nutrients(LOAF)


@pytest.mark.parametrize(
    ("panel", "reason"),
    [
        ({**LOAF, "kcal": None}, "no usable energy"),
        ({**LOAF, "kcal": 0}, "no usable energy"),
        ({**LOAF, "kcal": 950}, "pure fat"),
        ({"kcal": 200, "fat": 3.6, "carbohydrates": 38.4}, "has no protein"),
        ({**LOAF, "fat": -1}, "impossible"),
        (
            {"kcal": 200, "protein": 60, "fat": 60, "carbohydrates": 60},
            "macros",
        ),
        ({**LOAF, "carbohydrates": 120}, "100 g of"),
    ],
    ids=[
        "no-energy",
        "zero-energy",
        "denser-than-fat",
        "missing-macro",
        "negative",
        "macros-over-100g",
        "one-over-100g",
    ],
)
def test_a_panel_no_food_could_have_is_refused(panel, reason: str) -> None:
    """The figure is stored for years, so a wrong one is worse than none."""
    with pytest.raises(NutritionError, match=reason):
        assert_usable_nutrients(panel)


def test_an_optional_nutrient_is_checked_only_when_stated() -> None:
    """Absent is fine -- labels omit them -- but present and wrong is not."""
    assert_usable_nutrients({**LOAF, "sodium": 0.4})

    with pytest.raises(NutritionError, match="100 g of sodium"):
        assert_usable_nutrients({**LOAF, "sodium": 200})


def test_a_zero_calorie_panel_may_still_carry_sodium() -> None:
    """Table salt is genuinely 0 kcal and genuinely full of sodium."""
    stored = nutrients_for_storage({"sodium": 38.758}, zero_calorie=True)

    assert stored == {
        "kcal": 0.0,
        "protein": 0.0,
        "fat": 0.0,
        "carbohydrates": 0.0,
        "sodium": 38.758,
    }


def test_a_zero_calorie_panel_refuses_a_nutrient_that_carries_energy() -> None:
    """Sugar beside a zero energy is a contradiction, not a declaration."""
    with pytest.raises(NutritionError, match="conflicts"):
        nutrients_for_storage({"sugar": 2.2}, zero_calorie=True)


def test_a_zero_calorie_declaration_cannot_erase_stated_nutrition() -> None:
    with pytest.raises(NutritionError, match="conflicts"):
        nutrients_for_storage(LOAF, zero_calorie=True)


def test_a_panel_that_cannot_account_for_its_energy_is_flagged() -> None:
    """The mistake no ceiling can see, said out loud rather than refused.

    Stored anyway: 635 of the 11,885 frozen rows are unreconciled and most of
    them legitimately, so refusing would turn away one real product in
    nineteen.
    """
    assert_usable_nutrients(MISMATCHED)
    note = reconciliation_note(MISMATCHED)

    assert note is not None
    assert "460" in note and "707" in note


def test_a_panel_that_adds_up_is_not_flagged() -> None:
    """Otherwise the warning is noise and stops being read."""
    assert reconciliation_note(LOAF) is None


def test_alcohol_accounts_for_the_energy_no_macro_explains() -> None:
    """A cooking wine reads as a contradiction until its ethanol is stated.

    The shared library carries the 7 kcal a gram; what this pins is that a
    stated alcohol figure reaches it, because `alcohol` is a nutrient pantry
    stores rather than one of the three it requires.
    """
    wine = {"kcal": 88.4, "protein": 0.6, "fat": 0.0, "carbohydrates": 0.3}

    assert reconciliation_note(wine) is not None
    assert reconciliation_note({**wine, "alcohol": 12.1}) is None


def test_a_partial_macro_set_is_refused_before_it_is_reconciled() -> None:
    """Two of three can account for anything, so it is the wrong complaint."""
    partial = {"kcal": 200, "protein": 8.5, "fat": 3.6}

    assert reconciliation_note(partial) is None
    with pytest.raises(NutritionError, match="carbohydrates"):
        assert_usable_nutrients(partial)
