"""Ordering and filtering results, and what neither may quietly assume."""

from decimal import Decimal

from pantry.commands.search import _sorted


def result(name: str, **fields: object) -> dict:
    return {"name": name, **fields}


class TestProteinDensity:
    """Protein per 100 kcal: the reason to rank a catalogue at all."""

    def test_the_densest_comes_first(self) -> None:
        lean = result("Lean", kcal=Decimal("100"), protein=Decimal("20"))
        rich = result("Rich", kcal=Decimal("500"), protein=Decimal("10"))

        ordered = _sorted([rich, lean], "protein-per-kcal")

        assert [r["name"] for r in ordered] == ["Lean", "Rich"]

    def test_an_unknown_panel_sorts_last_rather_than_as_zero(self) -> None:
        """Nothing known is not the same as none of it."""
        known = result("Known", kcal=Decimal("100"), protein=Decimal("5"))
        unknown = result("Unknown", kcal=None, protein=None)

        ordered = _sorted([unknown, known], "protein-per-kcal")

        assert [r["name"] for r in ordered] == ["Known", "Unknown"]

    def test_a_zero_calorie_product_is_not_infinitely_dense(self) -> None:
        zero = result("Water", kcal=Decimal("0"), protein=Decimal("0"))
        real = result("Tofu", kcal=Decimal("100"), protein=Decimal("8"))

        ordered = _sorted([zero, real], "protein-per-kcal")

        assert [r["name"] for r in ordered] == ["Tofu", "Water"]

    def test_half_a_panel_cannot_be_ranked(self) -> None:
        half = result("Half", kcal=Decimal("100"), protein=None)
        whole = result("Whole", kcal=Decimal("100"), protein=Decimal("1"))

        ordered = _sorted([half, whole], "protein-per-kcal")

        assert [r["name"] for r in ordered] == ["Whole", "Half"]


def test_sorting_keeps_every_result() -> None:
    """A reorder is not a filter: nothing is dropped for being unrankable."""
    results = [
        result("A", kcal=Decimal("100"), protein=Decimal("1")),
        result("B"),
        result("C", kcal=Decimal("100"), protein=Decimal("9")),
    ]

    assert len(_sorted(results, "protein-per-kcal")) == 3
