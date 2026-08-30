"""Ranking: which record a plain query resolves to, and why."""

from decimal import Decimal

import pytest

from pantry.local import Local


def product(source: str, name: str, **fields: object) -> dict:
    return {"source": source, "id": f"{source}-{name}", "name": name,
            **fields}


class TestSourceTrust:
    """A composition record beats a branded one at equal name score."""

    def test_the_composition_database_wins_a_tie(self) -> None:
        rows = [
            product("coles", "Olive Oil"),
            product("afcd", "Olive Oil"),
        ]

        best = Local(rows).search("olive oil", limit=1)

        assert best[0]["source"] == "afcd"

    def test_a_hand_entered_record_beats_every_other_source(self) -> None:
        rows = [product("afcd", "Butter"), product("manual", "Butter")]

        best = Local(rows).search("butter", limit=1)

        assert best[0]["source"] == "manual"

    def test_trust_never_overrides_the_name_score(self) -> None:
        """A worse name is a worse answer, whoever supplied it."""
        rows = [
            product("afcd", "Olive Oil Rusk"),
            product("coles", "Olive Oil"),
        ]

        best = Local(rows).search("olive oil", limit=1)

        assert best[0]["name"] == "Olive Oil"


class TestCommaQualifiedNames:
    """`Oil, olive` is the same food as `Olive Oil`, written back to front."""

    def test_a_reversed_name_beats_a_longer_written_order_match(self) -> None:
        rows = [
            product("coles", "Olive Oil Rusk"),
            product("afcd", "Oil, olive"),
        ]

        best = Local(rows).search("olive oil", limit=1)

        assert best[0]["name"] == "Oil, olive"

    def test_a_qualifier_tail_does_not_sink_the_record(self) -> None:
        rows = [
            product("coles", "Cheddar Cheese Slices"),
            product("afcd", "Cheese, cheddar, natural, regular fat"),
        ]

        best = Local(rows).search("cheddar cheese", limit=1)

        assert best[0]["source"] == "afcd"

    def test_written_order_still_beats_an_unrelated_head(self) -> None:
        rows = [
            product("afcd", "Gravy, onion, brown"),
            product("coles", "Brown Onion"),
        ]

        best = Local(rows).search("brown onion", limit=1)

        assert best[0]["name"] == "Brown Onion"


class TestUnmatchedHead:
    """A head word the query never asked for names a different food."""

    def test_a_two_word_head_loses_to_the_food_itself(self) -> None:
        rows = [
            product("afcd", "Lemon peel, raw"),
            product("afcd", "Lemon, peeled, raw"),
        ]

        best = Local(rows).search("lemon", limit=1)

        assert best[0]["name"] == "Lemon, peeled, raw"

    def test_asking_for_the_second_head_word_brings_it_back(self) -> None:
        rows = [
            product("afcd", "Lemon peel, raw"),
            product("afcd", "Lemon, peeled, raw"),
        ]

        best = Local(rows).search("lemon peel", limit=1)

        assert best[0]["name"] == "Lemon peel, raw"


class TestUnrequestedQualifiers:
    """A plain query wants the plain food."""

    def test_a_preparation_nobody_asked_for_ranks_below_the_plain(
        self,
    ) -> None:
        rows = [
            product("afcd", "Garlic, peeled, fresh, fried, no added fat"),
            product("afcd", "Garlic, peeled, fresh, raw"),
        ]

        best = Local(rows).search("garlic", limit=1)

        assert best[0]["name"] == "Garlic, peeled, fresh, raw"

    def test_a_preserved_form_ranks_below_the_fresh_one(self) -> None:
        rows = [
            product("afcd", "Milk, cow, canned, evaporated, regular"),
            product("afcd", "Milk, cow, fluid, regular fat (~3.5%)"),
        ]

        best = Local(rows).search("milk", limit=1)

        assert "evaporated" not in best[0]["name"]

    def test_a_reduced_variant_ranks_below_the_regular_one(self) -> None:
        rows = [
            product("afcd", "Cheese, cheddar, natural, reduced fat (~25%)"),
            product("afcd", "Cheese, cheddar, natural, regular fat"),
        ]

        best = Local(rows).search("cheddar cheese", limit=1)

        assert best[0]["name"] == "Cheese, cheddar, natural, regular fat"

    def test_asking_for_the_preparation_still_finds_it(self) -> None:
        rows = [
            product("afcd", "Rice, white, boiled, no added salt"),
            product(
                "afcd", "Rice, white, fried with bacon or ham, egg, prawns"
            ),
        ]

        best = Local(rows).search("fried rice", limit=1)

        assert "fried" in best[0]["name"]

    def test_a_query_word_is_not_penalised_as_a_qualifier(self) -> None:
        rows = [
            product("afcd", "Oregano, dried"),
            product("afcd", "Oregano, fresh"),
        ]

        best = Local(rows).search("dried oregano", limit=1)

        assert best[0]["name"] == "Oregano, dried"


class TestLeftoverQualifiers:
    """Between two records the query fits equally, the narrower one loses."""

    def test_an_extra_qualifier_loses_to_the_bare_name(self) -> None:
        rows = [product("openfoodfacts", "Quail Eggs"),
                product("openfoodfacts", "eggs")]

        best = Local(rows).search("eggs", limit=1)

        assert best[0]["name"] == "eggs"

    def test_the_least_qualified_record_of_a_source_wins(self) -> None:
        rows = [
            product("afcd", "Oats, rolled, mixed with sugar or honey"),
            product("afcd", "Oats, rolled, uncooked"),
        ]

        best = Local(rows).search("rolled oats", limit=1)

        assert best[0]["name"] == "Oats, rolled, uncooked"


class TestPlurals:
    """A plural is the same word, and must not cost a record its place."""

    def test_a_plural_query_matches_the_singular_head_exactly(self) -> None:
        rows = [
            product("coles", "Speckled Easter Eggs"),
            product("afcd", "Egg, chicken, whole, raw"),
        ]

        best = Local(rows).search("eggs", limit=1)

        assert best[0]["name"] == "Egg, chicken, whole, raw"


class TestMatchConfidence:
    """How good the answer is, so a caller can decide to look elsewhere."""

    def test_every_result_says_how_well_it_matched(self) -> None:
        rows = [product("afcd", "Oil, olive")]

        found = Local(rows).search("olive oil", limit=1)

        assert found[0]["match"] == {"score": Decimal("1"),
                                     "tier": "composition"}

    def test_a_query_word_nothing_answered_lowers_the_score(self) -> None:
        rows = [product("afcd", "Rice, white, uncooked")]

        found = Local(rows).search("basmati rice", limit=1)

        assert found[0]["match"]["score"] < Decimal("0.6")

    def test_the_tier_names_the_kind_of_source(self) -> None:
        rows = [product("coles", "Chickpeas")]

        found = Local(rows).search("chickpeas", limit=1)

        assert found[0]["match"]["tier"] == "retail"

    def test_a_confidence_is_never_negative(self) -> None:
        """Penalties may exceed the score; a match is not worth less than 0."""
        rows = [product("afcd", "Rice paper wrapper, soaked in water")]

        found = Local(rows).search("rice", limit=1)

        assert found[0]["match"]["score"] >= 0

    def test_a_match_is_not_a_storable_field(self) -> None:
        """A search-result field, like `title` and `price` before it."""
        from pantry.products import assert_exportable_product

        with pytest.raises(Exception):
            assert_exportable_product(
                {"source": "afcd", "id": "F1", "name": "Oil, olive",
                 "match": {"score": Decimal("1"), "tier": "composition"}}
            )
