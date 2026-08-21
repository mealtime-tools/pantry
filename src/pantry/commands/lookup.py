"""`pantry lookup` — exact composite-identity lookup."""

import click
from agentcli import emit, json_option

from pantry.commands.describe import describe
from pantry.products import PRODUCT_SOURCES
from pantry.session import deps, guard, wants_json


def _human(payload: dict) -> list[str]:
    if not payload["found"]:
        return [f"no product found for {payload['source']}:{payload['id']}"]
    return [describe(payload["product"])]


@click.command("lookup")
@click.argument("source", type=click.Choice(PRODUCT_SOURCES))
@click.argument("product_id")
@json_option
@click.pass_context
def lookup(
    ctx: click.Context, source: str, product_id: str, json_output: bool
) -> None:
    """Find exactly SOURCE and PRODUCT_ID, with no fuzz and no network.

    A miss exits 1 while still emitting a full payload: identity is the pair,
    so `found: false` is a fact about that pair and not an error.
    """
    json_output = wants_json(ctx, json_output)

    with guard(json_output):
        product = deps(ctx).store.find(source, product_id)
        emit(
            {
                "found": product is not None,
                "source": source,
                "id": product_id,
                "product": product,
            },
            json_output=json_output,
            human=_human,
        )
        if product is None:
            raise SystemExit(1)
