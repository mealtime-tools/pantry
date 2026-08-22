"""The uniform provider surface: who is asked, and what claims a reference."""

import json

import pytest
from pantry.conftest import COLES_URL, FakeTransport, TransportRecorder

from pantry.providers import (
    Provider,
    Providers,
    resolve_reference,
)

HELD = {
    "source": "coles",
    "id": "1047",
    "name": "Example Bread",
    "brand": "",
    "kcal": 234.2,
    "protein": 8.5,
    "fat": 3.6,
    "carbs": 38.4,
}

# One Search-a-licious hit, in the shape the deployed index really returns.
OFF_HIT = {
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
            },
        }
    ]
}


class Fake(Provider):
    """A searchable provider whose credential is missing."""

    name = "usda"
    searchable = True

    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def search(self, query: str, limit: int) -> list[dict]:
        return [{"source": "usda", "id": "1"}]


def test_an_unconfigured_provider_is_skipped_silently() -> None:
    """Being unconfigured is not a failure, so it is not reported as one."""
    assert Providers([Fake(False)]).searchers(remote=True) == []

    configured = Fake(True)
    assert Providers([configured]).searchers(remote=True) == [configured]

    # And a remote provider stays out until the caller opts into the cost.
    assert Providers([configured]).searchers() == []


def test_search_is_local_until_remote_is_asked_for(make_deps, run) -> None:
    calls: list[str] = []

    def get(url: str) -> str:
        calls.append(url)
        return json.dumps(OFF_HIT)

    deps = make_deps([HELD], off_get=get)

    local = run(deps, "--json", "search", "example bread")
    assert local.exit_code == 0
    payload = json.loads(local.output)["data"]
    assert payload["sources"] == ["local"]
    assert [r["source"] for r in payload["results"]] == ["coles"]
    # The injected client was never asked: no network cost without --remote.
    assert calls == []

    remote = run(deps, "--json", "search", "example bread", "--remote")
    merged = json.loads(remote.output)["data"]
    assert merged["sources"] == ["local", "openfoodfacts"]
    assert [r["source"] for r in merged["results"]] == [
        "coles",
        "openfoodfacts",
    ]
    assert len(calls) == 1

    # --source restricts to one provider, and every result stays tagged.
    only = run(
        deps,
        "--json",
        "search",
        "yogurt",
        "--remote",
        "--source",
        "openfoodfacts",
    )
    restricted = json.loads(only.output)["data"]
    assert restricted["sources"] == ["openfoodfacts"]


def test_a_search_result_carries_sodium_only_when_it_is_held(
    make_deps, run
) -> None:
    salted = {**HELD, "id": "1048", "sodium": 400}
    deps = make_deps([HELD, salted])

    results = json.loads(run(deps, "--json", "search", "example bread").output)
    nutrients = {r["id"]: r["nutrients"] for r in results["data"]["results"]}

    # Milligrams, and absent rather than zero: the frozen shards predate the
    # field, and a defaulted 0 would read as a sodium-free product instead of
    # an unknown one.
    assert nutrients["1048"]["sodium"] == 400
    assert "sodium" not in nutrients["1047"]


def test_lookup_never_reaches_the_network(make_deps, run) -> None:
    """The whole point of the command: an exact answer at no cost."""
    recorder = TransportRecorder(FakeTransport("plain", []))
    deps = make_deps([HELD], open_transports=recorder)

    found = run(deps, "--json", "lookup", "coles", "1047")

    # Every injected client raises if it is used, so exit 0 is the proof.
    assert found.exit_code == 0
    assert json.loads(found.output)["data"]["found"] is True
    assert recorder.opened == []


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        (COLES_URL, ("retailer", "coles", "1047")),
        ("usda:2476857", ("usda", "usda", "2476857")),
        (
            "off:0123456789012",
            ("openfoodfacts", "openfoodfacts", "0123456789012"),
        ),
    ],
)
def test_a_reference_names_its_provider_and_its_identity(ref, expected):
    resolved = resolve_reference(ref)

    assert (resolved.provider, resolved.source, resolved.id) == expected


def test_an_open_food_facts_barcode_keeps_its_own_provenance(
    make_deps, run, store_path
):
    """Community data must not be filed as something the user read off a label.

    `manual` is a claim about where a number came from. Storing an Open Food
    Facts row under it would both lose that distinction and let the user's own
    entry for the same barcode silently overwrite it.
    """
    deps = make_deps([], off_get=lambda url: json.dumps(OFF_HIT))

    result = run(deps, "--json", "add", "off:0123456789012")

    assert result.exit_code == 0
    product = json.loads(result.output)["data"]["product"]
    assert (product["source"], product["id"]) == (
        "openfoodfacts",
        "0123456789012",
    )
    assert product["kcal"] == 59 and product["protein"] == 10.3
    assert "openfoodfacts.org/product/0123456789012" in product["url"]
    # Leading zeros are significant, and survive to the stored record.
    assert '"id":"0123456789012"' in (
        store_path / "openfoodfacts.jsonl"
    ).read_text(encoding="utf-8")


def test_a_community_row_with_no_energy_is_refused(make_deps, run, store_path):
    thin = {"hits": [{"code": "1", "product_name": "Mystery"}]}
    deps = make_deps([], off_get=lambda url: json.dumps(thin))

    result = run(deps, "add", "off:1")

    assert result.exit_code == 1
    assert "no usable energy" in result.output
    assert not (store_path / "openfoodfacts.jsonl").exists()
