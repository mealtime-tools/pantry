"""A catalogue survives a round trip, and a broken one says why."""

from decimal import Decimal
from pathlib import Path

import pytest
from agentcli import UsageError

from pantry.catalog import catalog_path, read_catalog, write_catalog
from pantry.data import read_shards

ENTRY = {
    "id": "9352792000258",
    "name": "Max Bean Silken Tofu 300g",
    "price": Decimal("4.29"),
    "pack_grams": Decimal("300"),
    "available": True,
    "tags": ["tofu"],
}


def test_a_catalogue_sits_beside_the_shards_without_being_one(
    tmp_path: Path,
) -> None:
    """A catalogue in the store directory must not read as product records.

    It holds prices and no nutrition, so a shard reader picking it up would
    put priced, panel-less rows into every search.
    """
    write_catalog(
        catalog_path(tmp_path, "umall"), [ENTRY], "2026-08-29T00:00Z"
    )

    assert read_shards(tmp_path) == []


def test_a_written_catalogue_reads_back_unchanged(tmp_path: Path) -> None:
    path = catalog_path(tmp_path, "umall")
    write_catalog(path, [ENTRY], "2026-08-29T09:00:00Z")

    document = read_catalog(path)

    assert document["fetched_at"] == "2026-08-29T09:00:00Z"
    assert document["products"] == [ENTRY]


def test_every_number_reads_back_as_a_decimal(tmp_path: Path) -> None:
    """A weight read as an int would make the division that prices it float."""
    path = catalog_path(tmp_path, "umall")
    write_catalog(path, [ENTRY], "2026-08-29T09:00:00Z")

    product = read_catalog(path)["products"][0]

    assert isinstance(product["price"], Decimal)
    assert isinstance(product["pack_grams"], Decimal)


def test_a_missing_catalogue_names_the_command_that_builds_one(
    tmp_path: Path,
) -> None:
    with pytest.raises(UsageError, match="pantry refresh"):
        read_catalog(catalog_path(tmp_path, "umall"))


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("{", "not valid JSON"),
        ("[]", "must contain a JSON object"),
        ('{"products":[]}', "missing fetched_at"),
        ('{"fetched_at":"x"}', "must contain a products array"),
    ],
)
def test_an_uninterpretable_catalogue_is_refused(
    tmp_path: Path, text: str, reason: str
) -> None:
    path = catalog_path(tmp_path, "umall")
    path.write_text(text, encoding="utf-8")

    with pytest.raises(UsageError, match=reason):
        read_catalog(path)


def test_a_refresh_replaces_rather_than_merges(tmp_path: Path) -> None:
    """A price the store no longer charges is not carried forward."""
    path = catalog_path(tmp_path, "umall")
    write_catalog(path, [ENTRY], "2026-08-29T09:00:00Z")
    write_catalog(path, [], "2026-08-30T09:00:00Z")

    assert read_catalog(path)["products"] == []
