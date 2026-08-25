"""`pantry delete` — drop one record from the user's own store.

Only the localstore is writable. A shipped shard row is refused rather than
hidden behind a tombstone, and deleting a correction uncovers the shard row it
was shadowing.
"""

import click
from agentcli import json_option

from pantry.commands.describe import describe
from pantry.local import as_result
from pantry.output import emit
from pantry.products import PRODUCT_SOURCES, rescale
from pantry.session import deps, guard, wants_json

_REASONS = {
    "shipped": "is a shipped record and cannot be deleted",
    "missing": "is not held in your store",
}


def _human(payload: dict) -> list[str]:
    label = f"{payload['source']}:{payload['id']}"
    if not payload["deleted"]:
        return [f"{label} {_REASONS[payload['reason']]}"]
    return [f"deleted {describe(payload['product'])}", *payload["notes"]]


@click.command("delete")
@click.argument("source", type=click.Choice(PRODUCT_SOURCES))
@click.argument("product_id")
@json_option
@click.pass_context
def delete(
    ctx: click.Context,
    source: str,
    product_id: str,
    json_output: bool,
) -> None:
    """Remove SOURCE and PRODUCT_ID from the localstore.

    A record only the frozen shards hold is refused: nothing writes to package
    data. Deleting one that shadowed a shard row leaves that row visible
    again, which the payload says.

    A refusal exits 1 while still emitting a full payload.
    """
    json_output = wants_json(ctx, json_output)

    with guard(json_output):
        state = deps(ctx)
        held = state.store.stored(source, product_id)
        if held is None:
            reason = (
                "shipped"
                if state.store.find(source, product_id)
                else "missing"
            )
            missed = _payload(False, reason, None, source, product_id)
            _emit(missed, json_output)
            raise SystemExit(1)

        state.store.remove(source, product_id)

        # Read back rather than assumed: what is visible now is the answer.
        shadowed = state.store.find(source, product_id)
        notes = (
            [f"the shipped record for {source}:{product_id} is visible again"]
            if shadowed
            else []
        )
        _emit(
            _payload(True, "deleted", held, source, product_id, notes=notes),
            json_output,
        )


def _payload(
    deleted: bool,
    reason: str,
    product: dict | None,
    source: str,
    product_id: str,
    *,
    notes: list[str] | None = None,
) -> dict:
    """The one shape both a deletion and a refusal answer in."""
    return {
        "deleted": deleted,
        "reason": reason,
        "source": source,
        "id": product_id,
        "product": rescale(as_result(product)) if product else None,
        "notes": notes or [],
    }


def _emit(payload: dict, json_output: bool) -> None:
    emit(payload, json_output=json_output, human=_human)
