"""The small public contract Pantry must keep."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from agentcli import UsageError
from click.testing import CliRunner
from mealtime_nutrients import CORE_NUTRIENTS

from pantry.cli import main
from pantry.commands.add import _read_input
from pantry.data import data_dir, read_shards
from pantry.local import as_result
from pantry.nutrition import nutrients_for_storage
from pantry.open_food_facts import _parse_hit
from pantry.products import (
    BASIS_GRAMS,
    MILLILITRE_NOTE,
    NUTRIENT_KEYS,
    PRODUCT_KEYS,
    PRODUCT_SOURCES,
    UNSTATED_UNIT_NOTE,
    assert_exportable_product,
    format_jsonl,
    parse_jsonl,
    record_keys,
    rescale,
)
from pantry.providers import Provider, Providers
from pantry.providers.local import LocalProvider
from pantry.providers.pages import Blocked, PageBudget, PageLoader
from pantry.session import Deps
from pantry.sites import ProductRef, build_record, parse_product_page
from pantry.store import Store
from pantry.usda import to_product

# A frozen shard row, which states no weight, and a row that states it.
_AFCD = {
    "source": "afcd",
    "id": "F000002",
    "name": "Oat bran, raw",
    "brand": "",
    "kcal": Decimal("79.3"),
    "protein": Decimal("16.2"),
    "fat": Decimal("0.8"),
    "carbs": Decimal("1.6"),
}

_COLES = {
    "source": "coles",
    "id": "1516814",
    "name": "Oat Puffs Cocoa",
    "brand": "Coles",
    "url": "https://www.coles.com.au/product/oat-puffs-300g-1516814",
    "kcal": 391,
    "protein": Decimal("32.1"),
    "fat": Decimal("2.8"),
    "carbs": Decimal("55.5"),
    "grams": 100,
}

# The same product on another basis, as `add --input` may still state it.
_PACK = {
    **_COLES,
    "kcal": 1173,
    "protein": Decimal("96.3"),
    "fat": Decimal("8.4"),
    "carbs": Decimal("166.5"),
    "grams": 300,
}


def _invoke(tmp_path: Path, args: list[str], json_output: bool = True):
    """Run one command over the two fixture records."""
    store = Store(lambda: [_AFCD, _COLES], tmp_path / "store")
    state = Deps(
        store=store,
        providers=Providers([LocalProvider(store)]),
        write_out=lambda path, text: None,
    )
    flags = ["--json"] if json_output else []
    return CliRunner().invoke(main, [*args, *flags], obj=state)


def _run(tmp_path: Path, args: list[str]) -> dict:
    """The payload of a command that had to succeed."""
    result = _invoke(tmp_path, args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["data"]


class _Shop(Provider):
    """One deterministic live-shop answer for command contract tests."""

    name = "umall"
    searchable = True

    def search(self, query: str, limit: int) -> list[dict]:
        return [
            {
                "source": "umall",
                "id": "1",
                "name": f"{query.title()} 250g",
                "brand": "Example",
                "grams": 100,
                "price": Decimal("2.50"),
                "match": {"score": Decimal("1"), "tier": "unknown"},
            }
        ][:limit]


def test_source_search_replaces_the_local_store(tmp_path: Path) -> None:
    store = Store(lambda: [_AFCD, _COLES], tmp_path / "store")
    state = Deps(
        store=store,
        providers=Providers([LocalProvider(store), _Shop()]),
        write_out=lambda path, text: None,
    )

    result = CliRunner().invoke(
        main,
        ["search", "tofu", "--source", "umall", "--json"],
        obj=state,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["data"]
    assert payload["sources"] == ["umall"]
    assert [row["source"] for row in payload["results"]] == ["umall"]


def test_search_help_exposes_only_the_source_selector() -> None:
    result = CliRunner().invoke(main, ["search", "--help"])

    assert result.exit_code == 0, result.output
    assert "--source" in result.output
    assert "--shop" not in result.output
    assert "--remote" not in result.output


def test_search_accepts_both_shard_vocabularies_and_omits_the_unstated() -> (
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
    # Unstated, so absent: an absent key and a null one say the same thing.
    assert "sodium" not in result


def test_results_carry_the_core_macros_and_every_stated_nutrient() -> None:
    """A nutrient a record holds must reach the caller, and named as stored.

    The four are asserted against the constant so widening the vocabulary
    cannot quietly drop one of them.
    """
    afcd_row = {
        "source": "afcd",
        "id": "F005580",
        "name": "Milk, cow, canned, evaporated, reduced fat (~2%)",
        "brand": "",
        "kcal": Decimal("90.8"),
        "sugar": Decimal("10.3"),
    }

    result = as_result(afcd_row)

    assert result["sugar"] == Decimal("10.3")
    assert set(CORE_NUTRIENTS) <= set(result)
    assert "calcium" not in result


def test_a_record_is_written_identity_first_then_the_macros() -> None:
    """Pantry no longer reorders the vocabulary; it depends on this one."""
    written = record_keys(_COLES)

    assert written[: len(PRODUCT_KEYS)] == PRODUCT_KEYS
    assert NUTRIENT_KEYS[: len(CORE_NUTRIENTS)] == CORE_NUTRIENTS


def test_no_shard_row_states_energy_in_kilojoules() -> None:
    """kJ is converted at import; a stored record holds kcal and only kcal."""
    products = read_shards(data_dir())

    assert products
    assert all("kj" not in product for product in products)


def test_shards_use_one_flat_item_format() -> None:
    products = read_shards(data_dir())

    assert len(products) >= 1_500
    assert all("kcal" in product for product in products)
    assert not any("nutrients" in product for product in products)
    assert not any("serving_size" in product for product in products)
    assert not any("serving_size_grams" in product for product in products)

    # Every shipped row is per 100 g, stated or by the absent-means-100 rule.
    assert all(
        product.get("grams", BASIS_GRAMS) == BASIS_GRAMS
        for product in products
    )


def test_reading_and_rewriting_a_shard_reproduces_it_byte_for_byte() -> None:
    """A shard cannot be regenerated, so a round trip must not touch one.

    Every present shard is checked, so a private `coles.jsonl` in a working
    checkout is covered without the shipped AFCD one ever being optional.
    """
    checked = 0

    for source in PRODUCT_SOURCES:
        path = data_dir() / f"{source}.jsonl"
        if not path.is_file():
            continue

        text = path.read_text(encoding="utf-8")
        rewritten = format_jsonl(parse_jsonl(text, source=source), source)
        assert rewritten == text, f"{path} would not be written back as it is"
        checked += 1

    assert checked, "no shard was there to check"


def test_manual_panel_is_json_with_null_and_alias_support() -> None:
    assert _read_input(
        '{"kcal":100,"protein":2,"fat":0,"carbs":4,"fiber":null}'
    ) == (
        {
            "kcal": Decimal("100"),
            "protein": Decimal("2"),
            "fat": Decimal("0"),
            "carbs": Decimal("4"),
        },
        None,
    )


def test_manual_input_refuses_a_kilojoule_figure() -> None:
    """kJ is not a stored key, so stating one is a mistake, not a synonym."""
    with pytest.raises(UsageError):
        _read_input('{"kcal":100,"kj":418.4}')


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
    # The row's pack size, whose only reader was the deleted scaling path.
    assert "quantity" not in hit


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


def _coles_page(title: str, size: str = "90g") -> str:
    """A product page carrying one nutrition column under `title`."""
    payload = {
        "props": {
            "pageProps": {
                "product": {
                    "name": "Bread",
                    "brand": "Bakery",
                    "size": size,
                    "nutrition": {
                        "breakdown": [
                            {"title": "Per serving", "nutrients": []},
                            {
                                "title": title,
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
    return (
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}</script>"
    )


def _woolworths_page(name: str = "Bread") -> str:
    """A product page whose one column is headed for both units."""
    column = "Quantity Per 100g / 100mL"
    payload = {
        "props": {
            "pageProps": {
                "pdDetails": {
                    "Product": {"Name": name, "Brand": "Woolworths"},
                    "NutritionalInformation": [
                        {"Name": "Energy", "Values": {column: "100kcal"}},
                        {"Name": "Protein", "Values": {column: "2g"}},
                    ],
                }
            }
        }
    }
    return (
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}</script>"
    )


_REF = ProductRef("coles", "1", "https://coles.com.au/product/food-1")
_WOOLIES_REF = ProductRef(
    "woolworths", "1", "https://woolworths.com.au/shop/productdetails/1"
)


def test_a_retailer_panel_is_stored_exactly_as_the_page_states_it() -> None:
    """The pack size is not read; there is nothing to scale to it."""
    product = parse_product_page(_REF, _coles_page("Per 100g"))

    assert product["kcal"] == 100
    assert product["fat"] == 0
    assert product["grams"] == BASIS_GRAMS
    assert "basis_note" not in product
    assert "basis" not in product


def test_a_millilitre_panel_records_how_it_was_read() -> None:
    """A drink's column is per 100 mL, taken as 100 g and said to be."""
    product = parse_product_page(_REF, _coles_page("Per 100mL", size="1L"))

    assert product["kcal"] == 100
    assert product["grams"] == BASIS_GRAMS
    assert product["basis_note"] == MILLILITRE_NOTE
    # Never stamped: no retailer page states one, absent already means as-sold.
    assert "basis" not in product


def test_a_qualified_column_states_nothing_about_how_it_was_read() -> None:
    """A prepared panel or a serving column is not a per-100 mL claim."""
    for title in (
        "Per 100mL as prepared",
        "Per Serving (100mL)",
        "100ml/serve",
    ):
        product = parse_product_page(_REF, _coles_page(title))

        assert "basis_note" not in product, title
        assert "basis" not in product, title


def test_a_woolworths_panel_is_read_from_its_one_per_hundred_column() -> None:
    product = parse_product_page(_WOOLIES_REF, _woolworths_page())

    assert product["kcal"] == 100
    assert product["protein"] == 2
    assert product["grams"] == BASIS_GRAMS


def test_a_woolworths_panel_records_that_its_unit_is_unstated() -> None:
    """One column headed for both units, so a solid and a drink read alike."""
    solid = parse_product_page(_WOOLIES_REF, _woolworths_page("Bread"))
    drink = parse_product_page(_WOOLIES_REF, _woolworths_page("Soy Milk 1L"))

    assert solid["basis_note"] == UNSTATED_UNIT_NOTE
    assert drink["basis_note"] == UNSTATED_UNIT_NOTE
    assert "basis" not in solid


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
    assert product["grams"] == BASIS_GRAMS
    assert "nutrients" not in product


def test_manual_input_is_normalized_to_the_one_stored_basis(
    tmp_path: Path,
) -> None:
    """A panel stated for a 90 g bar is stored, and read back, per 100 g."""
    store = Store(list, tmp_path / "store")
    state = Deps(
        store=store,
        providers=Providers([]),
        write_out=lambda path, text: None,
    )
    added = CliRunner().invoke(
        main,
        ["add", "--input", "-", "--id", "bar", "--name", "Bar", "--json"],
        input='{"grams":90,"kcal":335,"protein":45.6,"fat":7.9,"carbs":4.9}',
        obj=state,
    )

    assert added.exit_code == 0, added.output
    stored = store.find("manual", "bar")
    assert stored is not None
    # 335 / 0.9, at the one decimal place energy is stored to everywhere.
    assert stored["kcal"] == Decimal("372.2")
    assert stored["protein"] == Decimal("50.666667")
    assert stored["grams"] == BASIS_GRAMS

    # And what the caller is handed back is what went in, not a second reading.
    assert json.loads(added.output)["data"]["product"]["kcal"] == 372.2


def test_no_emitted_product_omits_the_weight_it_describes(
    tmp_path: Path,
) -> None:
    """Absence is what let a caller infer a basis, and infer it wrongly."""
    for record in (_AFCD, _COLES):
        assert rescale(as_result(record))["grams"] == BASIS_GRAMS

    looked = _run(tmp_path, ["lookup", "afcd", "F000002"])
    assert looked["product"]["grams"] == BASIS_GRAMS

    found = _run(tmp_path, ["search", "oat"])
    assert found["results"]
    assert all(result["grams"] == BASIS_GRAMS for result in found["results"])


def test_a_stored_record_and_the_wire_agree_figure_for_figure() -> None:
    """One shape, one basis: emitting must not restate anything."""
    shown = rescale(as_result(_COLES))

    for key in ("kcal", "protein", "fat", "carbs", "grams"):
        assert shown[key] == _COLES[key]


def test_restating_a_record_moves_every_stored_nutrient() -> None:
    """Energy included: a figure left behind reads as a different food."""
    per_hundred = rescale(_PACK)

    assert per_hundred["kcal"] == 391
    assert per_hundred["carbs"] == Decimal("55.5")
    assert per_hundred["protein"] == Decimal("32.1")
    assert per_hundred["grams"] == BASIS_GRAMS


def test_a_chosen_weight_becomes_the_basis_of_the_figures() -> None:
    assert rescale(as_result(_AFCD), 42)["kcal"] == Decimal("33.306")
    assert rescale(as_result(_AFCD), 42)["grams"] == 42

    scaled = rescale(as_result(_COLES), 42)
    assert scaled["kcal"] == Decimal("164.22")
    assert scaled["grams"] == 42

    # Asking for the default basis explicitly says so and changes nothing else.
    assert rescale(as_result(_COLES), 100)["kcal"] == 391


def test_a_chosen_weight_leaves_identity_alone() -> None:
    plain = as_result(_COLES)
    scaled = rescale(plain, 42)

    for key in ("id", "name", "title", "brand", "url", "source"):
        assert scaled.get(key) == plain.get(key)


def test_lookup_and_search_scale_to_the_requested_weight(
    tmp_path: Path,
) -> None:
    looked = _run(tmp_path, ["lookup", "coles", "1516814"])
    assert looked["product"]["kcal"] == 391

    looked = _run(tmp_path, ["lookup", "coles", "1516814", "--grams", "42"])
    assert looked["product"]["kcal"] == 164.22
    assert looked["product"]["grams"] == 42

    # One weight, every result: mixing bases across a result list is the bug.
    found = _run(tmp_path, ["search", "oat", "--grams", "42"])
    by_id = {result["id"]: result for result in found["results"]}
    assert by_id["1516814"]["kcal"] == 164.22
    assert by_id["F000002"]["kcal"] == 33.306
    assert all(result["grams"] == 42 for result in by_id.values())


def test_a_weight_that_is_not_a_weight_is_refused(tmp_path: Path) -> None:
    """`NaN` and `Infinity` are figures no strict parser will read back."""
    for value in ("nan", "-nan", "inf", "-inf", "Infinity", "0", "-1", "x"):
        result = _invoke(
            tmp_path, ["lookup", "afcd", "F000002", "--grams", value]
        )

        assert result.exit_code != 0, f"--grams {value}: {result.output}"
        assert "kcal" not in result.output


def test_a_weight_its_figures_cannot_survive_is_refused(
    tmp_path: Path,
) -> None:
    """Checked on the result: a weight can be finite and still ruin one."""
    for value in ("1e308", "5e-324", "1e999999"):
        for json_output in (True, False):
            result = _invoke(
                tmp_path,
                ["lookup", "coles", "1516814", "--grams", value],
                json_output,
            )
            where = f"--grams {value} (json={json_output})"

            assert result.exit_code != 0, f"{where}: {result.output}"
            assert "Infinity" not in result.output, where
            assert '"kcal":0' not in result.output, where
            # A refusal, not a traceback out of the arithmetic.
            assert result.exception is None or isinstance(
                result.exception, SystemExit
            ), f"{where}: {result.exception!r}"


def test_the_wire_carries_plain_json_numbers(tmp_path: Path) -> None:
    """A figure is a JSON number, so no consumer has to unwrap or parse one."""
    result = _invoke(tmp_path, ["lookup", "coles", "1516814", "--grams", "40"])

    assert result.exit_code == 0, result.output
    assert '"kcal":156.4' in result.output
    assert '"fat":1.12' in result.output
    assert '"grams":40' in result.output


def test_no_pack_size_reaches_the_output(tmp_path: Path) -> None:
    """The only weight in a payload is the one the figures describe."""
    found = _run(tmp_path, ["search", "oat"])
    looked = _run(tmp_path, ["lookup", "coles", "1516814"])

    for shown in [looked["product"], *found["results"]]:
        assert "serving_size_grams" not in shown
        assert "quantity" not in shown


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


def _added(tmp_path: Path, product_id: str, name: str) -> Deps:
    """A store holding the two fixtures plus one record of the user's own."""
    store = Store(lambda: [_AFCD, _COLES], tmp_path / "store")
    state = Deps(
        store=store,
        providers=Providers([LocalProvider(store)]),
        write_out=lambda path, text: None,
    )
    added = CliRunner().invoke(
        main,
        ["add", "--input", "-", "--id", product_id, "--name", name, "--json"],
        input='{"kcal":100,"protein":1,"fat":2,"carbs":3}',
        obj=state,
    )
    assert added.exit_code == 0, added.output
    return state


def test_delete_removes_only_the_users_own_record(tmp_path: Path) -> None:
    state = _added(tmp_path, "bar", "Bar")
    runner = CliRunner()

    args = ["delete", "manual", "bar", "--json"]
    deleted = runner.invoke(main, args, obj=state)

    assert deleted.exit_code == 0, deleted.output
    payload = json.loads(deleted.output)["data"]
    assert payload["deleted"] is True
    assert payload["product"]["name"] == "Bar"
    assert state.store.find("manual", "bar") is None

    # A second delete is a miss, not a second success.
    again = runner.invoke(main, args, obj=state)
    assert again.exit_code == 1
    assert json.loads(again.output)["data"]["deleted"] is False


def test_delete_refuses_a_shipped_record(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["delete", "afcd", "F000002"])

    assert result.exit_code == 1
    payload = json.loads(result.output)["data"]
    assert payload["deleted"] is False
    assert payload["reason"] == "shipped"
    # Still there: the frozen shards are not writable by any command.
    assert _run(tmp_path, ["lookup", "afcd", "F000002"])["found"] is True


def test_delete_says_when_a_shipped_record_becomes_visible_again(
    tmp_path: Path,
) -> None:
    """Deleting a correction restores the shard row it was shadowing."""
    store = Store(lambda: [_AFCD, _COLES], tmp_path / "store")
    state = Deps(
        store=store,
        providers=Providers([LocalProvider(store)]),
        write_out=lambda path, text: None,
    )
    corrected = CliRunner().invoke(
        main,
        [
            "add",
            "--input",
            "-",
            "https://www.coles.com.au/product/oat-puffs-300g-1516814",
            "--name",
            "Oat Puffs Cocoa",
            "--json",
        ],
        input='{"kcal":1,"protein":1,"fat":1,"carbs":1}',
        obj=state,
    )
    assert corrected.exit_code == 0, corrected.output

    deleted = CliRunner().invoke(
        main, ["delete", "coles", "1516814", "--json"], obj=state
    )

    assert deleted.exit_code == 0, deleted.output
    assert json.loads(deleted.output)["data"]["notes"]
    held = store.find("coles", "1516814")
    assert held is not None and held["kcal"] == 391


def test_a_keyed_panel_says_so_under_a_retailer_identity(
    tmp_path: Path,
) -> None:
    """A live recipe test stored two Coles records that a model had
    transcribed from a page the tool itself was blocked from loading. They
    were indistinguishable from fetched ones. Now they are not.
    """
    store = Store(lambda: [_AFCD, _COLES], tmp_path / "store")
    state = Deps(
        store=store,
        providers=Providers([LocalProvider(store)]),
        write_out=lambda path, text: None,
    )
    typed = CliRunner().invoke(
        main,
        [
            "add",
            "--input",
            "-",
            "https://www.coles.com.au/product/oat-puffs-300g-1516814",
            "--name",
            "Oat Puffs Cocoa",
            "--json",
        ],
        input='{"kcal":1,"protein":1,"fat":1,"carbs":1}',
        obj=state,
    )

    assert typed.exit_code == 0, typed.output
    assert json.loads(typed.output)["data"]["product"]["entered"] is True
    assert store.find("coles", "1516814")["entered"] is True


def test_a_fetched_panel_makes_no_such_claim() -> None:
    """Absent means read from the source, which is the ordinary case."""
    fetched = build_record(
        source="coles",
        product_id="1",
        name="X",
        brand="",
        panel={"kcal": 100},
    )

    assert "entered" not in fetched
