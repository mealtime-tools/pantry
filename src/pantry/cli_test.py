"""Rule 10, plus the search this whole package exists to answer."""

import json

import pytest

from pantry.data import data_dir, read_shards
from pantry.store import Store


def test_json_emits_exactly_one_object_with_the_documented_exit_codes(
    make_deps, run
) -> None:
    held = {
        "source": "manual",
        "id": "loaf",
        "name": "Loaf",
        "brand": "",
        "kcal": 239.0,
        "protein": 9.5,
        "fat": 3.4,
        "carbs": 39.2,
    }
    deps = make_deps([held])

    # A search that finds nothing is success with an empty list.
    empty = run(deps, "--json", "search", "nothing-matches-this-at-all")
    assert empty.exit_code == 0
    assert json.loads(empty.output)["data"]["results"] == []

    # A lookup miss is exit 1 and still one full payload, not an error.
    miss = run(deps, "--json", "lookup", "manual", "missing")
    assert miss.exit_code == 1
    assert json.loads(miss.output) == {
        "ok": True,
        "data": {
            "found": False,
            "source": "manual",
            "id": "missing",
            "product": None,
        },
    }

    # A refusal asked for with --json is one error object on stdout, so a
    # caller never has to merge two streams to find out what happened.
    scope = run(deps, "--json", "add", "--manual", "--id", "x", "--name", "X")
    assert scope.exit_code == 1
    refusal = json.loads(scope.output)
    assert refusal["ok"] is False
    assert list(refusal) == ["ok", "error"]

    # Without --json the same refusal goes to stderr, where stdout stays
    # clean for a human reading a terminal.
    nonsense = run(
        deps, "add", "--manual", "--id", "x", "--name", "X", stdin="nonsense"
    )
    assert nonsense.exit_code == 1
    assert "no usable energy" in nonsense.stderr
    assert nonsense.stdout == ""

    # And the flag works on either side of the subcommand.
    after = run(deps, "search", "loaf", "--json")
    assert json.loads(after.output)["data"]["results"][0]["id"] == "loaf"


def test_search_finds_greek_yogurt_in_the_real_database(store_path) -> None:
    if not (data_dir() / "coles.jsonl").is_file():
        pytest.skip("the Coles shard is not distributed with this checkout")
    store = Store(lambda: read_shards(data_dir()), store_path)

    results = store.search("greek yogurt", limit=5)

    # The real answer to this query is Chobani; a scoring change that loses it
    # is a regression a fixture would never catch.
    assert len(results) == 5
    assert any("Chobani" in result["title"] for result in results)
    assert all("yog" in result["title"].lower() for result in results)


def test_search_prefers_head_term_matches(store_path) -> None:
    store = Store(lambda: read_shards(data_dir()), store_path)

    # A query matching the head of a name must outscore matching a modifier,
    # so raw Cavendish banana beats branded banana-flavoured pouches.
    banana_results = store.search("banana", limit=6)
    assert any(
        r["source"] == "afcd" and r["id"] == "F000262"
        for r in banana_results[:3]
    )

    # Plain butter must outrank composite dishes like butter chicken sauce.
    butter_results = store.search("butter", limit=6)
    assert any(
        "butter, plain" in r["name"].lower() for r in butter_results[:3]
    )
    assert all("sauce" not in r["name"].lower() for r in butter_results[:3])
