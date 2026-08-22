"""What a panel's figures are measured against, and who gets told.

A prepared-basis panel is internally consistent — its energy, its macros and
its kilojoules all reconcile — so nothing else in this suite can catch it.
These tests pin the one thing that can: the record says so, and every way of
reading it back repeats what it said.
"""

import json

import pytest

from pantry.commands.describe import describe
from pantry.conftest import (
    COLES_URL,
    FakeTransport,
    TransportRecorder,
    coles_page,
)
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

# The issue's headline record as a retailer really serves it. The pack size is
# the figure the note converts from, so re-authoring must not cost it.
HELD_CUBES = {
    "source": "coles",
    "id": "98548",
    "name": "Vegetable Stock Cubes",
    "brand": "Massel",
    "kj": 23,
    "fat": 0.35,
    "carbs": 0.53,
    "protein": 0,
    "fiber": 0.035,
    "sugar": 0.32,
    "kcal": 5.5,
    "url": "https://www.coles.com.au/product/example-98548",
    "total_size": 105,
    "total_unit": "g",
}

CUBES_URL = "https://www.coles.com.au/product/example-98548"


def test_basis_round_trips_in_the_fixed_key_order() -> None:
    written = format_jsonl([PREPARED], source="manual")

    # Beside the figures it qualifies, and before the packaging fields: a
    # moved key would turn a one-product edit into a whole-file diff.
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


@pytest.mark.parametrize("note", ["", 0], ids=["empty", "zero"])
def test_a_note_with_no_text_renders_as_no_note(note) -> None:
    """A note is free text, so a shard may carry one that says nothing.

    Nothing validates the note, which means a hand-edited row — or an
    `--basis-note ""` that blanks one — can reach either output. Filtering on
    emptiness rather than absence keeps both surfaces honest: no dangling
    caveat for a person, no `"basis_note":""` in a documented result shape.
    """
    record = {**PREPARED, "basis_note": note}

    assert NOTE not in describe(record)
    assert "basis_note" not in as_result(record)
    assert as_result(record)["basis"] == "as_prepared"


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
    """Refused by the flag itself, before a record is ever built."""
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
    assert "Invalid value for '--basis'" in refused.stderr
    assert "as_sold" in refused.stderr and "as_prepared" in refused.stderr


@pytest.mark.parametrize(
    "flags",
    [("--basis", "as_prepared"), ("--basis-note", NOTE)],
    ids=["basis", "note"],
)
def test_a_basis_needs_the_manual_path(make_deps, run, flags) -> None:
    """Nothing on a retailer page or in an API response declares one.

    Checked before the reference is resolved, so a flag that cannot apply
    never costs a page load.
    """
    recorder = TransportRecorder(FakeTransport("plain", []))
    deps = make_deps([], open_transports=recorder)

    refused = run(deps, "add", COLES_URL, *flags)

    assert refused.exit_code == 1
    assert "--manual" in refused.stderr
    assert recorder.opened == []


def test_a_basis_note_needs_a_basis(make_deps, run) -> None:
    """A note without a flag reads as as-sold while its text says otherwise.

    An agent keyed on `basis` would scale by a dry weight with the correct
    conversion sitting beside it, which is the 47x error with extra steps.
    """
    deps = make_deps()
    refused = run(
        deps,
        "add",
        "--manual",
        "--id",
        "98548",
        "--name",
        "Vegetable Stock Cubes",
        "--basis-note",
        NOTE,
        stdin=PANEL,
    )

    assert refused.exit_code == 1
    assert "--basis" in refused.stderr


def test_a_malformed_basis_is_refused_on_the_way_in(
    make_deps, run, store_path
) -> None:
    """The one key checked on read as well as on write.

    An unrecognised value would otherwise fall back to "absent means
    as-sold", which is the silent undercount the key exists to prevent.
    """
    row = '{"id":"98548","name":"Cubes","brand":"","kcal":5.5,"protein":0,'

    with pytest.raises(ProductError, match="line 1"):
        parse_jsonl(row + '"basis":"as-prepared"}\n', source="manual")

    # And through the reader the CLI really uses, on a shard edited by hand.
    store_path.mkdir(parents=True, exist_ok=True)
    (store_path / "manual.jsonl").write_text(
        row + '"basis":"as-prepared"}\n', encoding="utf-8"
    )
    refused = run(make_deps(), "lookup", "manual", "98548")

    assert refused.exit_code == 1
    assert "basis" in refused.stderr


def test_a_visible_basis_mistake_stays_readable(
    make_deps, run, store_path
) -> None:
    """One bad row must never cost the shard it sits in.

    A note with no basis is already visible in `lookup` and `search` output,
    so refusing the file it sits in buys nothing and takes every other record
    down with it. Only the unrecognised basis value is worth failing a read,
    because it is the only mistake a reader cannot see.
    """
    legacy = (
        '{"id":"legacy","name":"Legacy","brand":"","kcal":5.5,"protein":0,'
        f'"fat":0,"carbs":0,"basis_note":"{NOTE}"}}\n'
    )
    good = (
        '{"id":"good","name":"Good","brand":"","kcal":100,"protein":5,'
        '"fat":2,"carbs":10}\n'
    )
    store_path.mkdir(parents=True, exist_ok=True)
    (store_path / "manual.jsonl").write_text(legacy + good, encoding="utf-8")

    # The unrelated record is still reachable, exactly as it is on main.
    unrelated = run(make_deps(), "lookup", "manual", "good")
    assert unrelated.exit_code == 0, unrelated.output
    assert "Good" in unrelated.output

    # And the note is visible on the record that carries it.
    shown = run(make_deps(), "lookup", "manual", "legacy")
    assert shown.exit_code == 0
    assert NOTE in shown.output


def test_re_adding_a_record_keeps_the_fields_the_paste_leaves_out(
    make_deps, run, store_path
) -> None:
    """Adding a basis to a held record must not cost the pack size.

    A paste says nothing about a pack size, a url or the rows it omits, and
    the pack size is exactly what the note's own conversion converts from.
    Silence is "unchanged", not "delete", which is what makes re-authoring a
    record the way to annotate one.
    """
    deps = make_deps([HELD_CUBES])

    added = run(
        deps,
        "add",
        "--manual",
        CUBES_URL,
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
    assert (store_path / "coles.jsonl").read_text(encoding="utf-8") == (
        '{"id":"98548","name":"Vegetable Stock Cubes","brand":"Massel",'
        '"kj":23,"fat":0.35,"carbs":0.53,"protein":0,"fiber":0.035,'
        f'"sugar":0.32,"kcal":5.5,"basis":"as_prepared","basis_note":"{NOTE}",'
        '"url":"https://www.coles.com.au/product/example-98548",'
        '"total_size":105,"total_unit":"g"}\n'
    )

    # Read back through the store: nothing was lost and the caveat is there.
    found = run(deps, "--json", "lookup", "coles", "98548")
    product = json.loads(found.output)["data"]["product"]
    assert product == {
        **HELD_CUBES,
        "basis": "as_prepared",
        "basis_note": NOTE,
    }


def test_a_refresh_keeps_a_hand_authored_basis(
    make_deps, run, store_path
) -> None:
    """No provider can put this field back, so a refresh must not drop it.

    Every other field is source-derived and re-supplied on refresh; a basis
    comes from nowhere but a human reading the pack.
    """
    recorder = TransportRecorder(
        FakeTransport(
            "plain",
            [
                (200, coles_page()),
                (200, coles_page(name="Example Bread Renamed")),
            ],
        )
    )
    deps = make_deps([], open_transports=recorder)

    assert run(deps, "add", COLES_URL).exit_code == 0
    annotated = run(
        deps,
        "add",
        "--manual",
        COLES_URL,
        "--name",
        "Example Bread",
        "--basis",
        "as_prepared",
        "--basis-note",
        NOTE,
        stdin=PANEL,
    )
    assert annotated.exit_code == 0, annotated.output

    changed = run(deps, "add", COLES_URL, "--refresh")

    assert changed.exit_code == 0, changed.output
    stored = (store_path / "coles.jsonl").read_text(encoding="utf-8")
    assert f'"basis":"as_prepared","basis_note":"{NOTE}"' in stored
    assert "Example Bread Renamed" in stored
