"""`pantry backfill` — give a catalogue's barcodes the panels they lack."""

from typing import Any

import click
from agentcli import json_option

from pantry.catalog import catalog_path, read_catalog
from pantry.diet import diet_path, read_diets, write_diets
from pantry.off_dump import harvest
from pantry.output import emit
from pantry.session import deps, guard, wants_json

RETAILERS = ("umall",)


def _human(payload: dict[str, Any]) -> list[str]:
    return [
        f"{payload['wanted']} barcodes to look for, "
        f"{payload['stored']} panels stored, {payload['diets']} diets known",
        f"{payload['unmatched']} were not in the export, "
        f"{payload['unusable']} were there with no usable panel",
    ]


@click.command("backfill")
@click.argument(
    "retailer", type=click.Choice(RETAILERS), default="umall", required=False
)
@json_option
@click.pass_context
def backfill(ctx: click.Context, retailer: str, json_output: bool) -> None:
    """Store Open Food Facts panels for the barcodes RETAILER sells.

    Reads the whole Open Food Facts export in one streaming pass, keeping only
    the rows whose barcode this catalogue lists. That is a large download, and
    it is the only way to answer tens of thousands of barcodes at once: the
    public index allows about ten searches a minute, which would take days.

    Most barcodes are not in the export, and that is reported rather than
    hidden. Nothing is invented for the ones that are missing.
    """
    json_output = wants_json(ctx, json_output)

    with guard(json_output):
        state = deps(ctx)

        catalogue = read_catalog(catalog_path(state.catalog_dir, retailer))
        wanted = {
            str(entry["id"])
            for entry in catalogue["products"]
            # Only a barcode another database could know. An in-store code
            # would match whatever product happens to share those digits.
            if entry.get("ref")
        }

        reaped = harvest(state.dump(), wanted)
        stored = state.store.add_all(reaped.records)

        # Merged, not replaced: a second retailer's backfill must not drop
        # what the first one learned about barcodes it does not sell.
        path = diet_path(state.catalog_dir)
        merged = {**read_diets(path), **reaped.diets}
        write_diets(path, merged, state.write_out)

        emit(
            {
                "retailer": retailer,
                "wanted": len(wanted),
                "stored": stored,
                "diets": len(reaped.diets),
                # Present in the export but with no panel worth storing.
                "unusable": reaped.matched - stored,
                "unmatched": len(wanted) - reaped.matched,
            },
            json_output=json_output,
            human=_human,
        )
