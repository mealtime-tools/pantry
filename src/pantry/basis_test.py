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
from pantry.store import Store

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
# the figure the note converts from, so annotating must not cost it.
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

# Pinned in full: the brackets, the separator and the order inside them are
# the whole warning, and a reader only sees them here.
PREPARED_LINE = (
    f"{'manual:98548':<20} {'6kcal 0p 1c 0f':<28} "
    f"Vegetable Stock Cubes (Massel)  [as_prepared: {NOTE}]"
)


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
    assert human.output.rstrip("\n") == PREPARED_LINE

    # Search projects a fixed shape, so the caveat has to be projected too.
    matched = run(deps, "--json", "search", "vegetable stock cubes")
    result = json.loads(matched.output)["data"]["results"][0]
    assert result["basis"] == "as_prepared"
    assert result["basis_note"] == NOTE

    listed = run(deps, "search", "vegetable stock cubes")
    assert listed.output.rstrip("\n") == PREPARED_LINE


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
    [("--basis", "as_prepared"), ("--basis-note", ""), ("--basis-note", NOTE)],
    ids=["basis", "empty-note", "note"],
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
    with pytest.raises(ProductError, match="basis_note"):
        assert_exportable_product({**AS_SOLD, "basis_note": NOTE})

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


def test_an_empty_basis_note_is_refused(make_deps, run) -> None:
    """A note that says nothing is a mistake, not a value.

    Stored, it would show as `"basis_note":""` under --json and as no note at
    all to a person, which is two different answers to the same question.
    """
    with pytest.raises(ProductError, match="basis_note"):
        assert_exportable_product({**PREPARED, "basis_note": ""})

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
        "as_prepared",
        "--basis-note",
        "",
        stdin=PANEL,
    )

    assert refused.exit_code == 1
    assert "basis_note" in refused.stderr


def test_a_malformed_basis_is_refused_on_the_way_in(
    make_deps, run, store_path
) -> None:
    """The one key checked on read as well as on write.

    An unrecognised value would otherwise fall back to "absent means
    as-sold", which is the silent undercount the key exists to prevent. It is
    the only basis rule enforced on read, because it is the only one a reader
    cannot see: `test_a_visible_basis_mistake_stays_readable` is the other
    half of this.
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
    """One bad row must never cost the shard, or the repair cannot run.

    A note with no basis, or an empty one, is already visible in `lookup` and
    `search` output, so refusing the file it sits in buys nothing and takes
    every other record down with it — `annotate` included, since finding a
    record means reading the whole shard first. Round one of this feature
    could write exactly this row, so it has to stay repairable.
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

    # The note is visible on the record that carries it, and it can be
    # repaired in place rather than by hand-editing JSONL.
    shown = run(make_deps(), "lookup", "manual", "legacy")
    assert shown.exit_code == 0
    assert NOTE in shown.output

    repaired = run(
        make_deps(), "annotate", "manual", "legacy", "--basis", "as_prepared"
    )
    assert repaired.exit_code == 0, repaired.output
    assert f'"basis":"as_prepared","basis_note":"{NOTE}"' in (
        store_path / "manual.jsonl"
    ).read_text(encoding="utf-8")

    # Still refused on the way out: the write path is where the note rules
    # belong, and reading a record is not authoring one.
    with pytest.raises(ProductError, match="basis_note"):
        assert_exportable_product({**AS_SOLD, "basis_note": NOTE})


@pytest.mark.parametrize(
    "note", ["", 0, False, []], ids=["empty", "zero", "false", "list"]
)
def test_a_note_with_no_text_renders_as_no_note(note) -> None:
    """The read path admits these; neither output may show a dangling note.

    The note rules live on the write path, so a hand-edited shard can carry a
    note that is present but says nothing. Filtering on emptiness rather than
    absence keeps both surfaces honest whatever the reader lets through, which
    is the property that stops a `[as_prepared: ]` or a Python repr reaching a
    human, and stops `"basis_note":""` reaching a documented result shape.
    """
    record = {**PREPARED, "basis_note": note}

    assert describe(record).endswith("(Massel)  [as_prepared]")
    assert "basis_note" not in as_result(record)
    assert as_result(record)["basis"] == "as_prepared"


# Every shape rule `update` still enforces on a record it did not author.
# `held` reaches it from `parse_jsonl`, which checks identity and the basis
# value and nothing else, so this is the floor under `annotate`.
MALFORMED = {
    "non-numeric kcal": {"kcal": "banana"},
    "negative kcal": {"kcal": -1},
    "missing kcal": {"kcal": None},
    "numeric id": {"id": 98548},
    "unsupported source": {"source": "aldi"},
    "missing name": {"name": None},
    "unsupported basis": {"basis": "prepared"},
    "empty note": {"basis": "as_prepared", "basis_note": "  "},
    "note with no basis": {"basis": None, "basis_note": NOTE},
}


@pytest.mark.parametrize("broken", MALFORMED.values(), ids=list(MALFORMED))
def test_an_edit_in_place_is_still_checked_for_shape(tmp_path, broken) -> None:
    """`update` drops plausibility, not shape.

    Without this floor a hand-edited shard would reach the writer intact: a
    record whose kcal is the string "banana" round-trips through the reader,
    and the failure lands wherever something first tries arithmetic on it.
    """
    store = Store(list, tmp_path)
    record = {**HELD_CUBES, "basis": "as_prepared", **broken}

    with pytest.raises(ProductError):
        store.update({k: v for k, v in record.items() if v is not None})

    assert not (tmp_path / "coles.jsonl").exists()


def test_annotating_a_held_record_keeps_every_other_field(
    make_deps, run, store_path
) -> None:
    """The repair path for a record already held, with no panel re-authored.

    Re-entering the panel by hand is what drops the pack size, and the pack
    size is what the note converts from.
    """
    deps = make_deps([HELD_CUBES])

    annotated = run(
        deps,
        "annotate",
        "coles",
        "98548",
        "--basis",
        "as_prepared",
        "--basis-note",
        NOTE,
    )

    assert annotated.exit_code == 0, annotated.output
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
    annotated = {**HELD_CUBES, "basis": "as_prepared", "basis_note": NOTE}
    assert product == annotated


def test_annotate_needs_a_held_record_and_a_basis(make_deps, run) -> None:
    deps = make_deps([HELD_CUBES])

    # Nothing to annotate is a refusal, not an add in disguise: this command
    # never reads a label and never touches the network.
    missing = run(deps, "annotate", "coles", "404", "--basis", "as_prepared")
    assert missing.exit_code == 1
    assert "is not held" in missing.output + missing.stderr

    # And a note alone cannot say which basis it describes.
    unpaired = run(deps, "annotate", "coles", "98548", "--basis-note", NOTE)
    assert unpaired.exit_code == 1
    assert "--basis" in unpaired.stderr


def test_a_note_cannot_outlive_the_basis_it_was_written_for(
    make_deps, run, store_path
) -> None:
    """Re-stating a different basis must not leave the old note behind.

    `as_sold` beside "per 100 mL prepared" is worse than no note at all: a
    consumer keyed on `basis` scales by the dry weight with the correction
    printed on the same line.
    """
    deps = make_deps(
        [{**HELD_CUBES, "basis": "as_prepared", "basis_note": NOTE}]
    )

    refused = run(deps, "annotate", "coles", "98548", "--basis", "as_sold")
    assert refused.exit_code == 1
    # Actionable: it names the conflict and the two ways out.
    assert "basis_note" in refused.stderr
    assert "--clear-basis-note" in refused.stderr
    assert not (store_path / "coles.jsonl").exists()

    # Either way out works, and the note is gone rather than contradicted.
    cleared = run(
        deps,
        "annotate",
        "coles",
        "98548",
        "--basis",
        "as_sold",
        "--clear-basis-note",
    )
    assert cleared.exit_code == 0, cleared.output
    stored = (store_path / "coles.jsonl").read_text(encoding="utf-8")
    assert '"basis":"as_sold"' in stored
    assert "basis_note" not in stored


def test_a_note_survives_re_stating_the_same_basis(
    make_deps, run, store_path
) -> None:
    """Absent means "leave it", not "delete it"."""
    deps = make_deps([HELD_CUBES])

    first = run(
        deps,
        "annotate",
        "coles",
        "98548",
        "--basis",
        "as_prepared",
        "--basis-note",
        NOTE,
    )
    assert first.exit_code == 0, first.output

    again = run(deps, "annotate", "coles", "98548", "--basis", "as_prepared")

    assert again.exit_code == 0, again.output
    assert f'"basis":"as_prepared","basis_note":"{NOTE}"' in (
        store_path / "coles.jsonl"
    ).read_text(encoding="utf-8")
    assert "null" not in (store_path / "coles.jsonl").read_text(
        encoding="utf-8"
    )


def test_clearing_and_setting_a_note_are_exclusive(make_deps, run) -> None:
    deps = make_deps([HELD_CUBES])

    refused = run(
        deps,
        "annotate",
        "coles",
        "98548",
        "--basis",
        "as_prepared",
        "--basis-note",
        NOTE,
        "--clear-basis-note",
    )

    assert refused.exit_code == 1
    assert "cannot be combined" in refused.stderr


def test_a_panel_todays_rules_would_refuse_can_still_be_annotated(
    make_deps, run, store_path, tmp_path
) -> None:
    """The rows that most need a basis are the ones strict validation refuses.

    141 frozen Coles rows fail today's nutrition rules, disproportionately dry
    goods — an instant coffee mix, ginger powder, vermicelli noodles. Their
    blocking signal, zero energy against non-zero macros on a shelf-stable dry
    good, is the prepared-basis signal. Refusing to annotate one would mean
    the only way to warn about it is to change its numbers.
    """
    unusable = {
        "source": "coles",
        "id": "8409346",
        "name": "G7 Strong Instant Coffee 3 In 1 Mix",
        "brand": "G7",
        "kcal": 0,
        "protein": 8,
        "fat": 0,
        "carbs": 0,
        "total_size": 320,
        "total_unit": "g",
    }
    deps = make_deps([unusable])

    annotated = run(
        deps,
        "annotate",
        "coles",
        "8409346",
        "--basis",
        "as_prepared",
        "--basis-note",
        "per 100 mL prepared; 1 sachet (16 g) makes 150 mL",
    )

    assert annotated.exit_code == 0, annotated.output
    stored = (store_path / "coles.jsonl").read_text(encoding="utf-8")
    # Annotating re-measures nothing: the figures are stored as they were.
    assert '"protein":8' in stored and '"kcal":0' in stored
    assert '"basis":"as_prepared"' in stored

    # Acquiring one is still refused: an edit in place is not a new import,
    # and only the edit is checked for shape alone.
    with pytest.raises(ProductError, match="zero energy"):
        assert_exportable_product(unusable)

    store = Store(list, tmp_path / "acquire")
    with pytest.raises(ProductError, match="zero energy"):
        store.add(unusable)
    store.update(unusable)


def test_a_refresh_keeps_a_hand_authored_basis(
    make_deps, run, store_path
) -> None:
    """No provider can put these two fields back, so a refresh must not
    delete them.

    Every other field is source-derived and re-supplied on refresh; a basis
    comes from nowhere but a human reading the pack.
    """
    same = coles_page()
    renamed = coles_page(name="Example Bread Renamed")
    recorder = TransportRecorder(
        FakeTransport("plain", [(200, same), (200, same), (200, renamed)])
    )
    deps = make_deps([], open_transports=recorder)

    assert run(deps, "add", COLES_URL).exit_code == 0
    assert (
        run(
            deps,
            "annotate",
            "coles",
            "1047",
            "--basis",
            "as_prepared",
            "--basis-note",
            NOTE,
        ).exit_code
        == 0
    )

    # An identical page is no change at all, so the record is left alone.
    again = run(deps, "add", COLES_URL, "--refresh")
    assert again.exit_code == 0
    assert "no field changes for coles:1047" in again.output

    # A page that did change is stored, and carries the annotation across.
    changed = run(deps, "add", COLES_URL, "--refresh")
    assert changed.exit_code == 0
    assert "Example Bread Renamed" in changed.output

    stored = (store_path / "coles.jsonl").read_text(encoding="utf-8")
    assert f'"basis":"as_prepared","basis_note":"{NOTE}"' in stored
    assert "Example Bread Renamed" in stored
