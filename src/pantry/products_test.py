"""Rules 1 and 7: the frozen bytes, how ids order, and the key order."""

import hashlib

import pytest

from pantry.data import data_dir
from pantry.products import (
    ProductError,
    assert_exportable_product,
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
        "eb55fa163c815301f8673e06e282c449deea9d12bde7e0f67e2b6930d187c12d",
    ),
    "afcd": (
        1588,
        "c59184d79adcabe49762e34514144f468ba1e0cdd5770da167f584e6f63a6455",
    ),
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


# Written with the nutrients first and out of order, so the write order has
# something to fix.
STOCK_CUBE = {
    "sodium": 17.75,
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


def test_vocabulary_nutrients_are_written_last_and_sorted() -> None:
    written = format_jsonl([STOCK_CUBE])

    # Structural first, then energy and the macros, then the nutrients in
    # alphabetical order. Sorting is what removes the need to enumerate them:
    # adding one diffs no other line, and a moved key is a whole-file diff.
    assert written.startswith(
        '{"source":"manual","id":"stock-cube",'
        '"name":"Vegetable Stock Cube","brand":"Example",'
        '"kcal":200,"protein":5,"fat":1,"carbs":40,'
        '"sodium":17.75,"sugar":2}'
    )


def test_a_record_with_no_sodium_stays_without_one() -> None:
    plain = {k: v for k, v in STOCK_CUBE.items() if k != "sodium"}

    # Optional, so its absence is not an error, and never filled with a zero
    # that would read as a sodium-free product.
    assert_product_record(plain)
    assert "sodium" not in format_jsonl([plain])
    assert parse_jsonl(format_jsonl([plain]))[0] == plain


@pytest.mark.parametrize("key", ["fiber", "sodium", "sugar"])
@pytest.mark.parametrize(
    "value",
    [-1, "355", float("inf"), 101],
    ids=["negative", "string", "infinite", "over-ceiling"],
)
def test_every_vocabulary_nutrient_is_checked_the_same_way(key, value) -> None:
    # One rule for all of them: grams per 100 g, so 100 is the ceiling. Pure
    # table salt is 38.758 g of sodium, so nothing edible is near it.
    with pytest.raises(ProductError, match=key):
        assert_product_record({**STOCK_CUBE, key: value})


def test_a_nutrient_name_outside_the_vocabulary_is_refused() -> None:
    # "sodum" would store cleanly and then no consumer would ever find the
    # sodium, which is the failure an open key set cannot detect.
    with pytest.raises(ProductError, match="sodum"):
        assert_product_record({**STOCK_CUBE, "sodum": 400})

    # And a refused key is never quietly dropped on the way out instead.
    with pytest.raises(ProductError, match="sodum"):
        format_jsonl([{**STOCK_CUBE, "sodum": 400}])


# Table salt: the record shape the zero-energy rules have to allow.
TABLE_SALT = {
    "source": "manual",
    "id": "table-salt",
    "name": "Table Salt",
    "brand": "Example",
    "kcal": 0,
    "protein": 0,
    "fat": 0,
    "carbs": 0,
    "sodium": 38.758,
}


def test_a_zero_energy_record_may_still_carry_sodium() -> None:
    # Sodium carries no energy, so it is the one figure the zero-energy
    # consistency check must not read as a contradiction.
    assert_exportable_product(TABLE_SALT)


def test_a_zero_energy_record_still_has_its_sodium_checked() -> None:
    # This branch returns before the panel rules run, which is why the ceiling
    # lives with the record checks that every authoring path reaches.
    with pytest.raises(ProductError, match="sodium"):
        assert_exportable_product({**TABLE_SALT, "sodium": 500})


def test_a_zero_energy_record_may_not_carry_a_nutrient_with_calories() -> None:
    # Sugar is exempt from nothing: a zero-energy record printing it is a
    # half-parsed panel, and three real Coles rows are exactly that shape.
    with pytest.raises(ProductError, match="sugar"):
        assert_exportable_product({**TABLE_SALT, "sugar": 27.2})
