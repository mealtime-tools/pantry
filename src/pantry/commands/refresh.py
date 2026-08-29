"""`pantry refresh` — rebuild a retailer's catalogue from its storefront."""

from typing import Any

import click
from agentcli import json_option

from pantry.catalog import catalog_path, write_catalog
from pantry.output import emit
from pantry.providers.umall import RETAILER
from pantry.session import deps, guard, wants_json
from pantry.umall import catalog_entry

# One retailer publishes a catalogue this cheaply. The argument exists so the
# second one does not change the command's shape.
RETAILERS = (RETAILER,)


def _human(payload: dict[str, Any]) -> list[str]:
    return [
        f"{payload['retailer']}: {payload['products']} products, "
        f"{payload['joinable']} with a barcode nutrition can be found by",
        f"written to {payload['path']} at {payload['fetched_at']}",
    ]


@click.command("refresh")
@click.argument(
    "retailer", type=click.Choice(RETAILERS), default=RETAILER, required=False
)
@json_option
@click.pass_context
def refresh(ctx: click.Context, retailer: str, json_output: bool) -> None:
    """Rebuild RETAILER's catalogue: what is on sale, and at what price.

    This is the one command here that always uses the network, because a
    price that was not just read is a guess. The catalogue is replaced rather
    than merged: a price the store no longer charges is not worth keeping.

    No nutrition is fetched. A row carries the barcode a panel could be found
    by, and `pantry add off:<barcode>` is what goes and gets one.
    """
    json_output = wants_json(ctx, json_output)

    with guard(json_output):
        state = deps(ctx)

        # Refused rows are counted rather than listed: they are a property of
        # the store's data, and naming a few thousand of them helps nobody.
        entries = []
        skipped = 0
        for node in state.sweep():
            entry = catalog_entry(node)
            if entry is None:
                skipped += 1
                continue
            entries.append(entry)

        fetched_at = state.now()
        path = catalog_path(state.catalog_dir, retailer)
        write_catalog(path, entries, fetched_at, state.write_out)

        emit(
            {
                "retailer": retailer,
                "fetched_at": fetched_at,
                "products": len(entries),
                # What a nutrition backfill could actually reach.
                "joinable": sum(
                    1 for entry in entries if entry.get("ref")
                ),
                "skipped": skipped,
                "path": str(path),
            },
            json_output=json_output,
            human=_human,
        )
