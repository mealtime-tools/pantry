"""The small public contract Pantry must keep."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pantry.cli import main
from pantry.commands.add import _read_input
from pantry.data import data_dir, read_shards
from pantry.local import as_result
from pantry.nutrition import nutrients_for_storage
from pantry.open_food_facts import _parse_hit
from pantry.products import assert_exportable_product
from pantry.providers import Providers
from pantry.providers.pages import Blocked, PageBudget, PageLoader
from pantry.session import Deps
from pantry.sites import ProductRef, build_record, parse_product_page
from pantry.store import Store
from pantry.usda import to_product


def test_search_accepts_both_shard_vocabularies_and_uses_null_for_missing() -> (
    None
):
    result = as_result(
        {
            "source": "coles",
            "id": "1",
            "name": "Food",
            "brand": "",
            "kcal": 0,
            "protein": 2,
            "fat": 3,
            "carbs": 4,
            "fiber": 5,
        }
    )

    assert result["kcal"] == 0
    assert result["protein"] == 2
    assert result["fat"] == 3
    assert result["fiber"] == 5
    assert result["sodium"] is None


def test_shards_use_one_flat_item_format() -> None:
    products = read_shards(data_dir())

    assert len(products) >= 1_500
    assert all("kcal" in product or "kj" in product for product in products)
    assert not any("nutrients" in product for product in products)
    assert not any("serving_size" in product for product in products)


def test_manual_panel_is_json_with_null_and_alias_support() -> None:
    assert _read_input(
        '{"kcal":100,"protein":2,"fat":0,"carbs":4,"fiber":null}'
    ) == (
        {"kcal": 100.0, "protein": 2.0, "fat": 0.0, "carbs": 4.0},
        None,
    )


def test_partial_panels_are_not_filled_with_zero() -> None:
    panel = nutrients_for_storage({"kcal": 0})
    product = build_record(
        source="manual",
        product_id="water",
        name="Water",
        brand="",
        panel=panel,
    )

    assert_exportable_product(product)
    assert as_result(product)["protein"] is None


def test_open_food_facts_keeps_only_reported_values() -> None:
    hit = _parse_hit(
        {
            "code": "123",
            "product_name": "Food",
            "nutriments": {"energy-kcal_100g": 10, "fat_100g": 0},
        }
    )

    assert hit is not None
    assert hit["fat"] == 0
    assert "protein" not in hit


def test_usda_keeps_only_reported_values() -> None:
    product = to_product(
        {
            "fdcId": 1,
            "description": "Food",
            "foodNutrients": [
                {"nutrient": {"id": 1008}, "amount": 10},
                {"nutrient": {"id": 1004}, "amount": 0},
            ],
        }
    )

    assert product["fat"] == 0
    assert "protein" not in product


def test_retailer_reader_uses_the_per_hundred_panel() -> None:
    payload = {
        "props": {
            "pageProps": {
                "product": {
                    "name": "Bread",
                    "brand": "Bakery",
                    "size": "90g",
                    "nutrition": {
                        "breakdown": [
                            {"title": "Per serving", "nutrients": []},
                            {
                                "title": "Per 100g",
                                "nutrients": [
                                    {"nutrient": "Energy", "value": "100kcal"},
                                    {"nutrient": "Protein", "value": "2g"},
                                    {"nutrient": "Fat", "value": "0g"},
                                    {
                                        "nutrient": "Carbohydrate",
                                        "value": "4g",
                                    },
                                ],
                            },
                        ]
                    },
                }
            }
        }
    }
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}</script>"
    )
    ref = ProductRef("coles", "1", "https://coles.com.au/product/food-1")

    product = parse_product_page(ref, html)

    assert product["grams"] == 90
    assert product["kcal"] == 90
    assert product["fat"] == 0


def test_input_and_lookup_use_the_canonical_product_shape(
    tmp_path: Path,
) -> None:
    store = Store(list, tmp_path / "store")
    state = Deps(
        store=store,
        providers=Providers([]),
        write_out=lambda path, text: None,
    )
    runner = CliRunner()
    added = runner.invoke(
        main,
        [
            "add",
            "--input",
            "-",
            "--id",
            "water",
            "--name",
            "Water",
            "--json",
        ],
        input='{"grams":90,"kcal":0,"protein":0}',
        obj=state,
    )

    assert added.exit_code == 0, added.output
    product = json.loads(added.output)["data"]["product"]
    assert product["protein"] == 0
    assert product["grams"] == 90
    assert "nutrients" not in product


def test_a_retailer_block_stops_the_loader() -> None:
    class Transport:
        name = "test"

        def load(self, url: str) -> tuple[int, str]:
            return (403, "blocked")

    loader = PageLoader([Transport()], PageBudget(2), 0)

    with pytest.raises(Blocked):
        loader.load("https://example.test")
    with pytest.raises(Blocked):
        loader.load("https://example.test")
    assert loader.spent == 1
