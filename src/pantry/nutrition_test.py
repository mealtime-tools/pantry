"""How a written nutrition row is read, row by row."""

from mealtime_nutrients import KJ_PER_KCAL

from pantry.nutrition import energy_to_kcal, panel_from_rows


def test_kilojoules_are_divided_by_the_published_ratio() -> None:
    """4.184 exactly. The old 0.239006 reciprocal was rounded, and wrong."""
    assert energy_to_kcal(1000, "kJ") == 1000 / KJ_PER_KCAL
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
