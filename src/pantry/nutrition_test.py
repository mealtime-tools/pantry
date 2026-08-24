"""How a written nutrition row is read, row by row."""

from mealtime_nutrients import KJ_PER_KCAL

from pantry.nutrition import energy_to_kcal


def test_kilojoules_are_divided_by_the_published_ratio() -> None:
    """4.184 exactly. The old 0.239006 reciprocal was rounded, and wrong."""
    assert energy_to_kcal(1000, "kJ") == 1000 / KJ_PER_KCAL
    assert energy_to_kcal(4184, "kj") == 1000
    assert energy_to_kcal(239, "kcal") == 239
