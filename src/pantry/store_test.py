"""Rule 9: where user data may land, and that base data is never written."""

import hashlib
from pathlib import Path

import pytest

from pantry.data import data_dir
from pantry.nutrition import NutritionError
from pantry.open_food_facts import cache_dir
from pantry.products import ProductError
from pantry.store import Store, store_dir

BASE = [
    {
        "source": "coles",
        "id": "1",
        "name": "One",
        "brand": "",
        "kcal": 100.0,
        "protein": 1.0,
        "fat": 1.0,
        "carbs": 1.0,
    },
    {
        "source": "coles",
        "id": "2",
        "name": "Two",
        "brand": "",
        "kcal": 100.0,
        "protein": 1.0,
        "fat": 1.0,
        "carbs": 1.0,
    },
]


def test_a_record_lands_in_the_shard_named_for_its_source(
    tmp_path: Path,
) -> None:
    """The filename carries the source, so the row does not repeat it."""
    store = Store(lambda: list(BASE), tmp_path)

    store.add(
        {
            "source": "manual",
            "id": "loaf",
            "name": "Loaf",
            "brand": "",
            "kcal": 100.0,
            "protein": 1.0,
            "fat": 1.0,
            "carbs": 1.0,
        }
    )

    written = (tmp_path / "manual.jsonl").read_text(encoding="utf-8")
    assert written.startswith('{"id":"loaf"')
    assert '"source"' not in written
    # Read back through the same reader the shipped data uses.
    assert store.find("manual", "loaf") is not None


def test_a_stored_row_shadows_one_base_row_not_the_whole_shard(
    tmp_path: Path,
) -> None:
    """Merging is per (source, id): rule 8 without an export to enforce it.

    The frozen rows took weeks of manual captcha-solving and nothing
    rebuilds them, so a store shard sharing a filename with a shipped one
    must not stand in for it.
    """
    store = Store(lambda: list(BASE), tmp_path)
    store.add({**BASE[0], "name": "One, corrected"})

    held = {(p["source"], p["id"]): p["name"] for p in store.all()}

    assert held[("coles", "1")] == "One, corrected"
    # The row that was not overridden survives.
    assert held[("coles", "2")] == "Two"


def test_user_data_stays_out_of_every_checkout(
    tmp_path: Path, make_deps, run
) -> None:
    # The XDG variable decides, and the fallback is the user's own config
    # directory: neither can resolve inside a repository by accident.
    env = {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    assert store_dir(env) == tmp_path / "xdg" / "pantry"
    assert store_dir({}, home=tmp_path) == tmp_path / ".config" / "pantry"

    # Disposable search data is separated from durable records by directory,
    # so clearing a cache can never take a user's own product with it.
    assert cache_dir({"XDG_CACHE_HOME": str(tmp_path / "x")}) == (
        tmp_path / "x" / "pantry" / "open-food-facts"
    )
    assert cache_dir({}, home=tmp_path) == (
        tmp_path / ".cache" / "pantry" / "open-food-facts"
    )

    # The shard is only present in a private checkout; the rest of this test
    # is about where user data lands, which holds either way.
    shard = data_dir() / "coles.jsonl"
    before = (
        hashlib.sha256(shard.read_bytes()).hexdigest()
        if shard.is_file()
        else None
    )

    panel = "Energy 1000kJ\nProtein 9.5g\nFat 3.4g\nCarbohydrate 39.2g"
    deps = make_deps(list(BASE))
    added = run(
        deps, "add", "--manual", "--id", "loaf", "--name", "Loaf", stdin=panel
    )
    assert added.exit_code == 0, added.output
    # It landed in the store, named for its source, and nowhere else.
    assert (
        (tmp_path / "config" / "pantry" / "manual.jsonl")
        .read_text(encoding="utf-8")
        .startswith('{"id":"loaf"')
    )

    # The frozen shard the run read from is untouched.
    if before is not None:
        after = hashlib.sha256(shard.read_bytes()).hexdigest()
        assert after == before


# A record carrying the one nutrient stored in milligrams, so the two write
# paths can be told apart by what they check about it.
SALTED = {
    "source": "manual",
    "id": "loaf",
    "name": "Loaf",
    "brand": "",
    "kcal": 100.0,
    "protein": 1.0,
    "fat": 1.0,
    "carbs": 1.0,
    "sodium": 400.0,
}


def test_annotating_a_record_carries_its_sodium_across(
    make_deps, run, store_path
) -> None:
    """`annotate` edits the basis and re-measures nothing."""
    deps = make_deps([SALTED])

    result = run(deps, "annotate", "manual", "loaf", "--basis", "as_prepared")

    assert result.exit_code == 0
    stored = (store_path / "manual.jsonl").read_text(encoding="utf-8")
    # In milligrams, in key order, and ahead of the basis it now carries.
    assert '"sodium":400,"kcal":100,"basis":"as_prepared"' in stored


def test_the_edit_path_checks_the_shape_of_a_sodium_it_did_not_author(
    tmp_path: Path,
) -> None:
    """What `Store.update` will and will not say about a sodium figure.

    `update` exists so a record whose panel today's rules would refuse can
    still be annotated, so it checks shape and not plausibility. That leaves
    the 100,000 mg ceiling to `add`, which is the only path that ever authors
    a sodium figure: `annotate` copies the held one verbatim and has no option
    to change it. A figure that is merely impossible is still refused here,
    because that is shape.
    """
    store = Store(lambda: [], tmp_path)

    for bad in (-1, "400", float("inf")):
        with pytest.raises(ProductError, match="sodium"):
            store.update({**SALTED, "sodium": bad})

    # Well-formed but implausible: tolerated on this path by design, the same
    # way a frozen row with impossible macros is. `add` is where it is caught.
    store.update({**SALTED, "sodium": 500_000.0})
    with pytest.raises(NutritionError, match="sodium"):
        store.add({**SALTED, "sodium": 500_000.0})
