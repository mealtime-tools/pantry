"""`pantry annotate` — say what a held record's figures are measured against.

The one thing no source supplies: whether its own panel was computed on the
product as sold or as prepared. A label states it in a column heading a
scraper never keeps, so recording it is a local edit to a record already held.

Separate from `add --manual` on purpose. That verb re-authors a record from a
panel, which is how a wrong field gets removed; it also drops every field the
new panel does not carry, and for a stock cube the field it drops is the pack
size the note's own conversion depends on.
"""

import click
from agentcli import UsageError, emit, json_option

from pantry.commands.describe import describe
from pantry.products import PRODUCT_BASES, PRODUCT_SOURCES, canonicalize
from pantry.session import deps, guard, wants_json


def _human(payload: dict) -> list[str]:
    return [f"annotated {describe(payload['product'])}"]


@click.command("annotate")
@click.argument("source", type=click.Choice(PRODUCT_SOURCES))
@click.argument("product_id")
@click.option(
    "--basis",
    type=click.Choice(PRODUCT_BASES),
    required=True,
    help="What the panel's figures are measured against.",
)
@click.option(
    "--basis-note",
    help="What a consumer must read before scaling, e.g. "
    '"per 100 mL prepared; 1 cube (10.5 g) makes 500 mL".',
)
@json_option
@click.pass_context
def annotate(
    ctx: click.Context,
    source: str,
    product_id: str,
    basis: str,
    basis_note: str | None,
    json_output: bool,
) -> None:
    """Set the basis of SOURCE and PRODUCT_ID in place, offline.

    Every other field is carried across untouched, so a record keeps the pack
    size and the url a re-entered panel would not have. The result lands in
    the localstore like any other addition, shadowing one base row and nothing
    more. An identity that is not held is a refusal rather than a fetch: this
    command never reads a label and never touches the network.
    """
    json_output = wants_json(ctx, json_output)

    with guard(json_output):
        state = deps(ctx)
        held = state.store.find(source, product_id)
        if held is None:
            raise UsageError(
                f"{source}:{product_id} is not held; add it first"
            )

        # An absent --basis-note leaves whatever the record already carried,
        # so re-stating a basis is not a way to lose a note by accident.
        changed = {"basis": basis}
        if basis_note is not None:
            changed["basis_note"] = basis_note

        product = canonicalize({**held, **changed})
        state.store.add(product)

        emit(
            {
                "annotated": True,
                "source": source,
                "id": product_id,
                "product": product,
            },
            json_output=json_output,
            human=_human,
        )
