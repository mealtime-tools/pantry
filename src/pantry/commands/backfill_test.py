"""`pantry backfill` gives a catalogue's barcodes the panels they lack."""

import json
from decimal import Decimal
from pathlib import Path

from click.testing import CliRunner

from pantry.catalog import catalog_path, write_catalog
from pantry.cli import main
from pantry.diet import diet_path, read_diets
from pantry.providers import Providers
from pantry.session import Deps
from pantry.store import Store, write_atomic

COLUMNS = (
    "code",
    "product_name",
    "brands",
    "ingredients_analysis_tags",
    "energy-kcal_100g",
    "proteins_100g",
    "fat_100g",
    "carbohydrates_100g",
)

# One catalogue row another database could know, and one the shop made up.
JOINABLE = {
    "id": "8850643003416",
    "name": "Por Kwan Pad Thai Sauce 225g",
    "brand": "Por Kwan",
    "price": Decimal("12.69"),
    "pack_grams": Decimal("225"),
    "available": True,
    "ref": "off:8850643003416",
}
IN_STORE = {
    "id": "9202402231777",
    "name": "Papaya - 1 Piece",
    "brand": "",
    "price": Decimal("6.89"),
    "available": True,
}


def export(*records: dict[str, str]) -> list[str]:
    header = "\t".join(COLUMNS)
    lines = [
        "\t".join(values.get(column, "") for column in COLUMNS)
        for values in records
    ]
    return [header, *lines]


def run(
    tmp_path: Path, entries: list[dict], lines: list[str]
) -> tuple[dict, Store]:
    write_catalog(
        catalog_path(tmp_path, "umall"), entries, "2026-08-29T09:00:00Z"
    )
    store = Store(lambda: [], tmp_path)
    state = Deps(
        store=store,
        providers=Providers([]),
        write_out=lambda path, text: write_atomic(Path(path), text),
        catalog_dir=tmp_path,
        dump=lambda: iter(lines),
    )
    result = CliRunner().invoke(main, ["backfill", "--json"], obj=state)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["data"], store


ROW = {
    "code": "8850643003416",
    "product_name": "Por Kwan Sour And Spicy Sauce",
    "brands": "Por Kwan",
    "ingredients_analysis_tags": "en:vegan,en:vegetarian",
    "energy-kcal_100g": "300",
    "proteins_100g": "6.67",
    "fat_100g": "13.33",
    "carbohydrates_100g": "40",
}


def test_a_matching_row_becomes_a_stored_panel(tmp_path: Path) -> None:
    payload, store = run(tmp_path, [JOINABLE], export(ROW))

    assert payload["stored"] == 1
    held = store.find("openfoodfacts", "8850643003416")
    assert held is not None
    assert held["kcal"] == Decimal("300")


def test_an_in_store_barcode_is_never_looked_for(tmp_path: Path) -> None:
    """Those digits belong to some other manufacturer's product."""
    payload, _ = run(tmp_path, [JOINABLE, IN_STORE], export(ROW))

    assert payload["wanted"] == 1


def test_a_barcode_the_export_lacks_is_reported_not_invented(
    tmp_path: Path,
) -> None:
    missing = {**JOINABLE, "id": "9999999999999", "ref": "off:9999999999999"}

    payload, store = run(tmp_path, [JOINABLE, missing], export(ROW))

    assert payload["wanted"] == 2
    assert payload["stored"] == 1
    assert payload["unmatched"] == 1
    assert store.find("openfoodfacts", "9999999999999") is None


def test_the_diet_is_written_beside_the_records(tmp_path: Path) -> None:
    payload, _ = run(tmp_path, [JOINABLE], export(ROW))

    assert payload["diets"] == 1
    assert read_diets(diet_path(tmp_path)) == {"8850643003416": "vegan"}


def test_a_second_backfill_keeps_what_the_first_learned(
    tmp_path: Path,
) -> None:
    """A diet map is about barcodes, not about one retailer's catalogue."""
    run(tmp_path, [JOINABLE], export(ROW))

    other = {**JOINABLE, "id": "4001724819394", "ref": "off:4001724819394"}
    other_row = {
        **ROW,
        "code": "4001724819394",
        "product_name": "Something Else",
        "ingredients_analysis_tags": "en:non-vegetarian",
    }
    run(tmp_path, [other], export(other_row))

    assert read_diets(diet_path(tmp_path)) == {
        "8850643003416": "vegan",
        "4001724819394": "non-vegetarian",
    }


def test_a_run_with_no_export_refuses_rather_than_guessing(
    tmp_path: Path,
) -> None:
    write_catalog(
        catalog_path(tmp_path, "umall"), [JOINABLE], "2026-08-29T09:00:00Z"
    )
    state = Deps(
        store=Store(lambda: [], tmp_path),
        providers=Providers([]),
        write_out=lambda path, text: None,
        catalog_dir=tmp_path,
    )

    result = CliRunner().invoke(main, ["backfill", "--json"], obj=state)

    assert result.exit_code == 1
    assert "no product export" in result.output


def test_a_backfill_needs_a_catalogue_first(tmp_path: Path) -> None:
    state = Deps(
        store=Store(lambda: [], tmp_path),
        providers=Providers([]),
        write_out=lambda path, text: None,
        catalog_dir=tmp_path,
        dump=lambda: iter(export(ROW)),
    )

    result = CliRunner().invoke(main, ["backfill", "--json"], obj=state)

    assert result.exit_code == 1
    assert "pantry refresh" in result.output
