"""Rules 1 and 7: the frozen bytes, how ids order, and the key order."""

import hashlib

import pytest

from pantry.data import data_dir
from pantry.products import (
    ProductError,
    assert_product_record,
    format_jsonl,
    parse_jsonl,
)

# Measured, not theoretical. `coles.jsonl` came from a scrape that no longer
# exists and cannot be regenerated, so any change to the serializer that would
# rewrite it has to fail here instead.
SHARDS = {
    "coles": (
        10297,
        "9d8eaa3b32f9775006e36710cfcf323a011c8a6b0aa48736db67d10d0bc8d7f6",
    ),
    "afcd": (
        1588,
        "53938eec2e627db56666df8abca04f6bc1dca844fb8decbfea32cfaa762d775a",
    ),
}

# Written with sodium first, so the fixed key order has something to fix.
STOCK_CUBE = {
    "sodium": 17750.0,
    "source": "manual",
    "id": "stock-cube",
    "name": "Vegetable Stock Cube",
    "brand": "Example",
    "sugar": 2.0,
    "kcal": 200.0,
    "protein": 5.0,
    "fat": 1.0,
    "carbs": 40.0,
}


@pytest.mark.parametrize("source", sorted(SHARDS))
def test_frozen_shards_reserialize_byte_identically(source: str) -> None:
    rows, digest = SHARDS[source]
    path = data_dir() / f"{source}.jsonl"
    if not path.is_file():
        pytest.skip(
            f"the {source} shard is not distributed with this checkout"
        )
    raw = path.read_bytes()

    assert hashlib.sha256(raw).hexdigest() == digest

    products = parse_jsonl(raw.decode("utf-8"), source=source, label=source)
    assert len(products) == rows

    # Row 8520 of the Coles shard carries "fiber":0.00001, which `json.dumps`
    # would write as 1e-05: this comparison is what pins the JS float format,
    # the key order and the record order all at once.
    assert format_jsonl(products, source=source).encode("utf-8") == raw


def test_leading_zero_ids_stay_distinct_and_sort_by_length() -> None:
    ids = ["10", "9", "09", "0009"]
    products = [
        {
            "source": "manual",
            "id": i,
            "name": i,
            "brand": "",
            "kcal": 1.0,
            "protein": 0.0,
            "fat": 0.0,
            "carbs": 0.0,
        }
        for i in ids
    ]

    written = [
        line.split('"id":"')[1].split('"')[0]
        for line in format_jsonl(products).splitlines()
    ]

    # Length before codepoint, and "09" never collapses into "9".
    assert written == ["9", "09", "10", "0009"]


def test_sodium_is_written_in_milligrams_between_sugar_and_kcal() -> None:
    written = format_jsonl([STOCK_CUBE])

    # Milligrams, unlike every gram figure beside it, and in the one position
    # the key order allows: a moved key is a whole-file diff.
    assert '"sugar":2,"sodium":17750,"kcal":200' in written


def test_a_record_with_no_sodium_stays_without_one() -> None:
    plain = {k: v for k, v in STOCK_CUBE.items() if k != "sodium"}

    # Optional, so its absence is not an error, and never filled with a zero
    # that would read as a sodium-free product.
    assert_product_record(plain)
    assert "sodium" not in format_jsonl([plain])
    assert parse_jsonl(format_jsonl([plain]))[0] == plain


@pytest.mark.parametrize(
    "value", [-1, "355", float("inf")], ids=["negative", "string", "infinite"]
)
def test_an_unusable_sodium_is_refused_rather_than_dropped(value) -> None:
    with pytest.raises(ProductError, match="sodium"):
        assert_product_record({**STOCK_CUBE, "sodium": value})
