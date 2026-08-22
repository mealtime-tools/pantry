"""What a panel's figures are measured against, and who gets told.

A prepared-basis panel is internally consistent — its energy, its macros and
its kilojoules all reconcile — so nothing else in this suite can catch it.
These tests pin the one thing that can: the record says so, and every way of
reading it back repeats what it said.
"""

import json

import pytest

from pantry.commands.describe import describe
from pantry.local import as_result
from pantry.products import (
    ProductError,
    assert_exportable_product,
    format_jsonl,
    parse_jsonl,
)

# The stock cube from the issue: 5.5 kcal per 100 mL of made-up stock, not per
# 100 g of cube. Scaling one 10.5 g cube by the stored figure undercounts 47x.
PREPARED = {
    "source": "manual",
    "id": "98548",
    "name": "Vegetable Stock Cubes",
    "brand": "Massel",
    "kj": 23,
    "fat": 0.35,
    "carbs": 0.53,
    "protein": 0,
    "kcal": 5.5,
    "basis": "as_prepared",
    "basis_note": "per 100 mL prepared; 1 cube (10.5 g) makes 500 mL",
    "url": "https://example.com/ultracube-vegetable",
    "total_size": 105,
    "total_unit": "g",
}

AS_SOLD = {
    "source": "manual",
    "id": "loaf",
    "name": "Loaf",
    "brand": "",
    "kcal": 239.0,
    "protein": 9.5,
    "fat": 3.4,
    "carbs": 39.2,
}

PANEL = "Energy 23kJ\nProtein 0g\nFat 0.35g\nCarbohydrate 0.53g"

NOTE = "per 100 mL prepared; 1 cube (10.5 g) makes 500 mL"


def test_basis_round_trips_in_the_fixed_key_order() -> None:
    written = format_jsonl([PREPARED], source="manual")

    # Beside the figures it qualifies, and before the packaging fields.
    assert written == (
        '{"id":"98548","name":"Vegetable Stock Cubes","brand":"Massel",'
        '"kj":23,"fat":0.35,"carbs":0.53,"protein":0,"kcal":5.5,'
        f'"basis":"as_prepared","basis_note":"{NOTE}",'
        '"url":"https://example.com/ultracube-vegetable",'
        '"total_size":105,"total_unit":"g"}\n'
    )

    read_back = parse_jsonl(written, source="manual")
    assert read_back == [PREPARED]


@pytest.mark.parametrize(
    "basis", ["as-prepared", "prepared", "AS_PREPARED", "", True]
)
def test_an_unknown_basis_is_refused(basis) -> None:
    with pytest.raises(ProductError, match="basis"):
        assert_exportable_product({**PREPARED, "basis": basis})


def test_a_basis_note_must_be_text() -> None:
    with pytest.raises(ProductError, match="basis_note"):
        assert_exportable_product({**PREPARED, "basis_note": 500})


@pytest.mark.parametrize("basis", ["as_sold", "as_prepared"])
def test_both_defined_bases_are_accepted(basis: str) -> None:
    assert_exportable_product({**PREPARED, "basis": basis})


def test_a_record_with_no_basis_behaves_exactly_as_before() -> None:
    """The compatibility guarantee: absent means as-sold, and stays absent.

    Writing a default into the record would rewrite the frozen shards, and a
    consumer that has never heard of the key has to keep working.
    """
    assert_exportable_product(AS_SOLD)

    assert format_jsonl([AS_SOLD], source="manual") == (
        '{"id":"loaf","name":"Loaf","brand":"","fat":3.4,"carbs":39.2,'
        '"protein":9.5,"kcal":239}\n'
    )

    result = as_result(AS_SOLD)
    assert "basis" not in result and "basis_note" not in result

    # No caveat is appended, so the human line is the one it always was.
    assert describe(result) == (
        f"{'manual:loaf':<20} {'239kcal 10p 39c 3f':<28} Loaf"
    )


def test_basis_reaches_both_output_formats(make_deps, run) -> None:
    deps = make_deps([PREPARED])

    found = run(deps, "--json", "lookup", "manual", "98548")
    assert found.exit_code == 0
    product = json.loads(found.output)["data"]["product"]
    assert product["basis"] == "as_prepared"
    assert product["basis_note"] == NOTE

    # A person reading a terminal is told on the same line as the figures.
    human = run(deps, "lookup", "manual", "98548")
    assert "as_prepared" in human.output and NOTE in human.output

    # Search projects a fixed shape, so the caveat has to be projected too.
    matched = run(deps, "--json", "search", "vegetable stock cubes")
    result = json.loads(matched.output)["data"]["results"][0]
    assert result["basis"] == "as_prepared"
    assert result["basis_note"] == NOTE

    listed = run(deps, "search", "vegetable stock cubes")
    assert "as_prepared" in listed.output and NOTE in listed.output


def test_manual_add_records_the_basis_it_is_told(
    make_deps, run, store_path
) -> None:
    deps = make_deps()
    added = run(
        deps,
        "add",
        "--manual",
        "--id",
        "98548",
        "--name",
        "Vegetable Stock Cubes",
        "--brand",
        "Massel",
        "--basis",
        "as_prepared",
        "--basis-note",
        NOTE,
        stdin=PANEL,
    )

    assert added.exit_code == 0, added.output
    written = (store_path / "manual.jsonl").read_text(encoding="utf-8")
    assert written.endswith(
        f'"kcal":5.5,"basis":"as_prepared","basis_note":"{NOTE}"}}\n'
    )


def test_an_unknown_basis_is_refused_at_the_command_line(
    make_deps, run
) -> None:
    deps = make_deps()
    refused = run(
        deps,
        "add",
        "--manual",
        "--id",
        "98548",
        "--name",
        "Vegetable Stock Cubes",
        "--basis",
        "prepared",
        stdin=PANEL,
    )

    assert refused.exit_code == 1


def test_a_basis_needs_the_manual_path(make_deps, run) -> None:
    """Nothing on a retailer page or in an API response declares one."""
    deps = make_deps()
    refused = run(
        deps,
        "add",
        "https://www.coles.com.au/product/example-bread-450g-1047",
        "--basis",
        "as_prepared",
    )

    assert refused.exit_code == 1
    assert "--manual" in refused.stderr
