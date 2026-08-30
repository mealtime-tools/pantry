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
