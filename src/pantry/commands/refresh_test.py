"""`pantry refresh` builds a catalogue the next search can read."""

import json
from pathlib import Path

from click.testing import CliRunner

from pantry.catalog import catalog_path, read_catalog
from pantry.cli import main
from pantry.providers import Providers
from pantry.providers.umall import UmallProvider
from pantry.session import Deps
from pantry.store import Store, write_atomic

NODE = {
    "handle": "max-bean-silken-tofu-300g",
    "title": "Max Bean Silken Tofu 300g",
    "vendor": "Max Bean",
    "productType": "Tofu",
    "tags": ["tofu"],
    "variants": {
        "nodes": [
            {
                "barcode": "9352792000258",
                "weight": 300.0,
                "weightUnit": "GRAMS",
                "availableForSale": True,
                "price": {"amount": "4.29", "currencyCode": "AUD"},
            }
        ]
    },
}

# No barcode, so it has no identity a catalogue could hold it under.
UNUSABLE = {**NODE, "variants": {"nodes": [{"barcode": None}]}}


def run(tmp_path: Path, nodes: list[dict], args: list[str]) -> dict:
    """Invoke the CLI against a sweep that returns `nodes` and no network."""
    store = Store(lambda: [], tmp_path)
    state = Deps(
        store=store,
        providers=Providers(
            [UmallProvider(store, catalog_path(tmp_path, "umall"))]
        ),
        write_out=lambda path, text: write_atomic(Path(path), text),
        catalog_dir=tmp_path,
        sweep=lambda: iter(nodes),
        now=lambda: "2026-08-29T09:00:00Z",
    )
    result = CliRunner().invoke(main, args, obj=state)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["data"]


def test_a_sweep_becomes_a_catalogue(tmp_path: Path) -> None:
    payload = run(tmp_path, [NODE], ["refresh", "--json"])

    assert payload["products"] == 1
    assert payload["fetched_at"] == "2026-08-29T09:00:00Z"
    document = read_catalog(catalog_path(tmp_path, "umall"))
    assert document["products"][0]["id"] == "9352792000258"


def test_a_row_with_no_identity_is_counted_not_held(tmp_path: Path) -> None:
    payload = run(tmp_path, [NODE, UNUSABLE], ["refresh", "--json"])

    assert payload["products"] == 1
    assert payload["skipped"] == 1


def test_the_report_says_how_many_could_be_given_nutrition(
    tmp_path: Path,
) -> None:
    """The number that matters before a backfill: what a join could reach."""
    internal = {
        **NODE,
        "variants": {
            "nodes": [
                {
                    **NODE["variants"]["nodes"][0],
                    "barcode": "9202402231777",
                }
            ]
        },
    }

    payload = run(tmp_path, [NODE, internal], ["refresh", "--json"])

    assert payload["products"] == 2
    assert payload["joinable"] == 1


def test_a_non_food_listing_is_left_out(tmp_path: Path) -> None:
    """A catalogue of face cream is a wrong denominator, not a smaller one."""
    cream = {**NODE, "productType": "Face Care"}

    payload = run(tmp_path, [NODE, cream], ["refresh", "--json"])

    assert payload["products"] == 1
    assert payload["excluded"] == 1
    assert payload["skipped"] == 0


def test_a_refresh_replaces_the_previous_catalogue(tmp_path: Path) -> None:
    run(tmp_path, [NODE], ["refresh", "--json"])
    run(tmp_path, [], ["refresh", "--json"])

    assert read_catalog(catalog_path(tmp_path, "umall"))["products"] == []


def test_the_catalogue_is_what_search_then_reads(tmp_path: Path) -> None:
    """The two halves meet: a refresh is what makes the provider answer."""
    run(tmp_path, [NODE], ["refresh", "--json"])

    store = Store(lambda: [], tmp_path)
    umall = UmallProvider(store, catalog_path(tmp_path, "umall"))

    [result] = umall.search("tofu", 10)

    assert result["name"] == "Max Bean Silken Tofu 300g"
    assert result["price_at"] == "2026-08-29T09:00:00Z"


def test_a_run_with_no_storefront_refuses_rather_than_guessing() -> None:
    """The default `sweep` exists so a test harness cannot silently refresh."""
    runner = CliRunner()
    with runner.isolated_filesystem() as directory:
        store = Store(lambda: [], Path(directory))
        state = Deps(
            store=store,
            providers=Providers([]),
            write_out=lambda path, text: None,
            catalog_dir=Path(directory),
        )
        result = runner.invoke(main, ["refresh", "--json"], obj=state)

    assert result.exit_code == 1
    assert "no storefront" in result.output
