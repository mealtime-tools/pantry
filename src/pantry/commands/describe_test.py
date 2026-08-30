"""The human line: dense, and unchanged for a source that states no price."""

from decimal import Decimal

from pantry.commands.describe import describe

PANEL = {
    "source": "coles",
    "id": "5185209",
    "title": "Tofu (Pureland)",
    "kcal": Decimal("108"),
    "protein": Decimal("14"),
    "carbs": Decimal("0"),
    "fat": Decimal("5"),
}


def test_a_source_with_no_price_reads_exactly_as_before() -> None:
    assert describe(PANEL) == (
        "coles:5185209        108kcal 14p 0c 5f            Tofu (Pureland)"
    )


def test_a_priced_result_says_what_it_costs() -> None:
    line = describe(
        {**PANEL, "price": Decimal("4.29"), "price_per_100g": Decimal("1.43")}
    )

    assert "$4.29 (1.43/100g)" in line


def test_a_price_with_no_weight_still_shows_the_pack_price() -> None:
    """Produce sold by the piece has a price and no unit price."""
    line = describe({**PANEL, "price": Decimal("6.89")})

    assert "$6.89" in line
    assert "/100g" not in line


def test_a_unit_price_is_rounded_for_the_eye_only() -> None:
    """The payload keeps the places a division produced; the line does not."""
    line = describe(
        {
            **PANEL,
            "price": Decimal("6.49"),
            "price_per_100g": Decimal("1.4295"),
        }
    )

    assert "(1.43/100g)" in line


def test_an_unknown_macro_stays_a_question_mark_beside_a_price() -> None:
    """A price says nothing about the panel, so it must not fill one in."""
    line = describe(
        {
            "source": "umall",
            "id": "9352792000258",
            "title": "Max Bean Silken Tofu 300g",
            "price": Decimal("4.29"),
        }
    )

    assert "?kcal ?p ?c ?f" in line
    assert "$4.29" in line


def test_a_weak_match_is_marked_where_a_person_will_see_it() -> None:
    """The store answered, but not with what was asked for."""
    line = describe(
        {**PANEL, "match": {"score": Decimal("0.4"), "tier": "composition"}}
    )

    assert line.endswith("~weak")


def test_a_good_match_reads_exactly_as_an_unscored_one() -> None:
    line = describe(
        {**PANEL, "match": {"score": Decimal("1"), "tier": "composition"}}
    )

    assert line == describe(PANEL)
