"""The barcode-to-diet map, and the store's bulk write beneath it."""

from decimal import Decimal
from pathlib import Path

import pytest
from agentcli import UsageError

from pantry.diet import diet_path, read_diets, write_diets
from pantry.products import ProductError
from pantry.store import Store


def product(barcode: str, **fields: object) -> dict:
    return {
        "source": "openfoodfacts",
        "id": barcode,
        "name": f"Product {barcode}",
        "brand": "",
        "kcal": Decimal("100"),
        "protein": Decimal("5"),
        "fat": Decimal("1"),
        "carbs": Decimal("10"),
        "grams": 100,
        **fields,
    }


class TestDiets:
    """A small map, written by a backfill and read by any search."""

    def test_a_map_survives_a_round_trip(self, tmp_path: Path) -> None:
        path = diet_path(tmp_path)
        write_diets(path, {"123": "vegan", "456": "non-vegetarian"})

        assert read_diets(path) == {"123": "vegan", "456": "non-vegetarian"}

    def test_no_map_yet_is_empty_rather_than_an_error(
        self, tmp_path: Path
    ) -> None:
        """A catalogue is searchable before any backfill has run."""
        assert read_diets(diet_path(tmp_path)) == {}

    def test_an_unreadable_map_is_refused(self, tmp_path: Path) -> None:
        path = diet_path(tmp_path)
        path.write_text("{not json", encoding="utf-8")

        with pytest.raises(UsageError):
            read_diets(path)

    def test_a_map_that_is_not_an_object_is_refused(
        self, tmp_path: Path
    ) -> None:
        path = diet_path(tmp_path)
        path.write_text("[]", encoding="utf-8")

        with pytest.raises(UsageError, match="must contain a JSON object"):
            read_diets(path)


class TestAddAll:
    """Storing a backfill's worth of records without rewriting per record."""

    def test_every_record_is_stored(self, tmp_path: Path) -> None:
        store = Store(lambda: [], tmp_path)

        assert store.add_all([product("1"), product("2")]) == 2
        assert store.find("openfoodfacts", "2") is not None

    def test_a_record_replaces_the_one_it_shares_an_identity_with(
        self, tmp_path: Path
    ) -> None:
        store = Store(lambda: [], tmp_path)
        store.add_all([product("1", kcal=Decimal("100"))])

        store.add_all([product("1", kcal=Decimal("250"))])

        held = store.find("openfoodfacts", "1")
        assert held is not None
        assert held["kcal"] == Decimal("250")

    def test_records_already_held_are_kept(self, tmp_path: Path) -> None:
        store = Store(lambda: [], tmp_path)
        store.add_all([product("1")])

        store.add_all([product("2")])

        assert store.find("openfoodfacts", "1") is not None
        assert store.find("openfoodfacts", "2") is not None

    def test_one_bad_record_stores_none_of_them(self, tmp_path: Path) -> None:
        """Validated up front: a refusal leaves no half-written shard."""
        store = Store(lambda: [], tmp_path)
        bad = product("3")
        bad["source"] = "nowhere"

        with pytest.raises(ProductError):
            store.add_all([product("1"), bad])

        assert store.find("openfoodfacts", "1") is None

    def test_storing_nothing_writes_nothing(self, tmp_path: Path) -> None:
        store = Store(lambda: [], tmp_path)

        assert store.add_all([]) == 0
        assert not (tmp_path / "openfoodfacts.jsonl").exists()
