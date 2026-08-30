"""Ranking: which record a plain query resolves to, and why."""

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
