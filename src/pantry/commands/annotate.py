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
from pantry.products import (
    PRODUCT_BASES,
    PRODUCT_SOURCES,
    Product,
    canonicalize,
)
from pantry.session import deps, guard, wants_json


def _human(payload: dict) -> list[str]:
    return [f"annotated {describe(payload['product'])}"]


def _annotated(held: Product, basis: str, note: str | None) -> Product:
    """The held record with its basis set, and its note dealt with.

    `note` is replacement text, `""` a request to drop the note, and None
    "leave whatever is there" — because re-stating a basis must not be a way
    to lose a note by accident.
    """
    product = {**held, "basis": basis}

    if note is None:
        _refuse_stale_note(held, basis)
        return product
    if note:
        return {**product, "basis_note": note}

    product.pop("basis_note", None)
    return product


def _refuse_stale_note(held: Product, basis: str) -> None:
    """Refuse to leave a note explaining figures on a different basis.

    `as_sold` beside "per 100 mL prepared" is worse than no note at all: a
    consumer keyed on `basis` scales by a dry weight with the correction
    printed beside it. A record carrying a note but no basis is the one case
    where adopting it is right — that shape is what this verb repairs.
    """
    stale = held.get("basis_note")
    if stale is None or held.get("basis") in (None, basis):
        return

    raise UsageError(
        f"{held['source']}:{held['id']} carries a basis_note written for "
        f"{held['basis']}: {stale!r}. Pass --basis-note to replace it, or "
        f"--clear-basis-note to drop it"
    )


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
@click.option(
    "--clear-basis-note",
    is_flag=True,
    help="Drop the note the record carries. The only way to remove one, "
    "since an empty note is refused.",
)
@json_option
@click.pass_context
def annotate(
    ctx: click.Context,
    source: str,
    product_id: str,
    basis: str,
    basis_note: str | None,
    clear_basis_note: bool,
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
        if basis_note is not None and clear_basis_note:
            raise UsageError(
                "--clear-basis-note cannot be combined with --basis-note"
            )

        state = deps(ctx)
        held = state.store.find(source, product_id)
        if held is None:
            raise UsageError(
                f"{source}:{product_id} is not held; add it first"
            )

        # Canonical for the payload's sake; the shard writer orders its own.
        note = "" if clear_basis_note else basis_note
        product = canonicalize(_annotated(held, basis, note))

        # Not `add`: this record was not acquired and nothing about it was
        # re-measured, so it is checked for shape rather than plausibility.
        state.store.update(product)

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
