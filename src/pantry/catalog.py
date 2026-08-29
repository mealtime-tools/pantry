"""A retailer's catalogue: what is on sale, at what price, right now.

Deliberately not a shard. A shard holds nutrition, which stays true, and is
merged into every search; a catalogue holds prices, which decay within a week,
and is read only when asked for. `read_shards` walks `PRODUCT_SOURCES` by
name, so this file sitting beside them is invisible to it, which is the
intent rather than an accident.

The whole catalogue is rewritten by a refresh. There is no per-row update: a
price the store no longer charges is not worth merging forward.
"""

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from agentcli import UsageError

from pantry.jsonfmt import dumps
from pantry.store import write_atomic

# One file per retailer, named so a shard reader walking sources skips it.
CATALOG_SUFFIX = ".catalog.json"


def catalog_path(store: Path, retailer: str) -> Path:
    """Where one retailer's catalogue lives, beside the user's own shards."""
    return store / f"{retailer}{CATALOG_SUFFIX}"


def write_catalog(
    path: Path,
    entries: list[dict[str, Any]],
    fetched_at: str,
    write: Callable[[Path, str], None] = write_atomic,
) -> None:
    """Replace a catalogue with what the sweep just read.

    Stamped, because every price in it is only true as of that moment and a
    reader has no other way to tell how old the answer is.
    """
    document = {"fetched_at": fetched_at, "products": entries}
    write(path, dumps(document) + "\n")


def read_catalog(path: Path) -> dict[str, Any]:
    """Read a catalogue, refusing one that cannot be interpreted.

    Every number is read as a `Decimal`. A price that arrived as a float would
    have lost the digits it was printed with, and a weight parsed as an `int`
    turns the division that prices it into float arithmetic.
    """
    if not path.is_file():
        raise UsageError(
            f"no catalogue at {path}; run `pantry refresh` to build one"
        )

    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            parse_float=Decimal,
            parse_int=Decimal,
        )
    except OSError as exc:
        raise UsageError(
            f"could not read {path}: {exc.strerror or exc}"
        ) from None
    except json.JSONDecodeError as exc:
        raise UsageError(f"{path} is not valid JSON: {exc}") from None

    if not isinstance(document, dict):
        raise UsageError(f"{path} must contain a JSON object")
    if not isinstance(document.get("fetched_at"), str):
        raise UsageError(f"{path} is missing fetched_at")
    if not isinstance(document.get("products"), list):
        raise UsageError(f"{path} must contain a products array")

    return document
