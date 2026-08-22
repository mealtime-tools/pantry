"""Discovery caching: one day of reuse, on an injected clock."""

import json
import urllib.parse
from pathlib import Path

import pytest

from pantry.open_food_facts import OpenFoodFacts, RemoteFailure

HIT = {
    "hits": [
        {
            "code": "0123456789012",
            "product_name": "Plain Greek Yogurt",
            "brands": "Example",
            "quantity": "907 g",
            "serving_size": "170 g",
            "nutriments": {
                "energy-kcal_100g": 59,
                "proteins_100g": 10.3,
                "fat_100g": 0.4,
                "carbohydrates_100g": 3.6,
                "sodium_100g": 0.036,
            },
        },
        {"code": "", "product_name": "Unidentifiable"},
    ]
}


def test_a_successful_search_is_reused_for_a_day_then_refetched(tmp_path):
    calls: list[str] = []
    clock = {"now": 1_000.0}

    def get(url: str) -> str:
        calls.append(url)
        return json.dumps(HIT)

    off = OpenFoodFacts(tmp_path / "off", get=get, now=lambda: clock["now"])

    first = off.search("greek yogurt", limit=5)
    assert len(calls) == 1
    assert first[0]["id"] == "0123456789012"
    assert first[0]["source"] == "openfoodfacts"
    # A leading zero in a barcode is significant and survives as a string.
    assert first[0]["nutrients"]["kcal"] == 59
    # A row that identifies nothing is dropped rather than half-stored.
    assert len(first) == 1

    # The query is credential-free and asks the index to boost the phrase.
    assert "boost_phrase=true" in calls[0] and "langs=en" in calls[0]

    # Inside the window the cached answer is returned with no request.
    clock["now"] += 23 * 60 * 60
    assert off.search("greek yogurt", limit=5) == first
    assert len(calls) == 1

    # Past it, one fresh request. Nothing was written to the localstore
    # records either
    # way: these are discovery candidates, not records.
    clock["now"] += 2 * 60 * 60
    off.search("greek yogurt", limit=5)
    assert len(calls) == 2


def test_sodium_is_converted_from_the_grams_the_index_publishes(tmp_path):
    off = OpenFoodFacts(tmp_path / "off", get=lambda url: json.dumps(HIT))

    hit = off.search("greek yogurt", limit=1)[0]

    # Open Food Facts publishes sodium in grams and a record stores it in
    # milligrams, so 0.036 g is 36 mg: passing it straight through would
    # under-report by a thousand.
    assert hit["nutrients"]["sodium"] == 36


def test_the_requested_page_size_is_clamped_not_passed_through(tmp_path):
    """A limit of zero costs no request, and a huge one asks for 100 rows."""
    calls: list[str] = []

    def get(url: str) -> str:
        calls.append(url)
        return json.dumps(HIT)

    off = OpenFoodFacts(tmp_path / "off", get=get, now=lambda: 0.0)

    assert off.search("greek yogurt", limit=0) == []
    assert calls == []

    off.search("greek yogurt", limit=1000)
    query = urllib.parse.urlparse(calls[0]).query
    assert urllib.parse.parse_qs(query)["page_size"] == ["100"]


def test_a_failure_is_not_cached_and_not_retried(tmp_path: Path) -> None:
    def get(url: str) -> str:
        return "not json"

    off = OpenFoodFacts(tmp_path / "off", get=get, now=lambda: 0.0)

    with pytest.raises(RemoteFailure):
        off.search("anything", limit=5)
    assert not list((tmp_path / "off").glob("*.json"))
