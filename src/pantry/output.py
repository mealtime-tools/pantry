"""One JSON object on stdout, in the same digits the records hold.

`agentcli.emit` serializes with `json.dumps`, which cannot write a `Decimal`
at all. The wire and the shards carry the same figures, so they get the same
serializer; the envelope is `agentcli`'s, unchanged, because that is the
contract every mealtime tool answers in.
"""

from collections.abc import Callable, Iterable
from typing import Any

import click

from pantry.jsonfmt import dumps


def emit(
    data: dict[str, Any],
    *,
    json_output: bool,
    human: Callable[[dict[str, Any]], Iterable[str]],
) -> None:
    """Write one successful result, in whichever format was requested."""
    if json_output:
        click.echo(dumps({"ok": True, "data": data}))
        return

    for line in human(data):
        click.echo(line)
