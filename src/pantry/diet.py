"""What an ingredient list implies about a barcode, kept beside the records.

This is Open Food Facts' conclusion, not a nutrient, so it has no place in a
product record — `_ALLOWED_KEYS` is closed, and a record is the same object
the other mealtime tools read as the shared item format. It is also not a
retailer's fact, so it does not belong in a catalogue either: the same barcode
means the same thing whoever is selling it, and a catalogue is replaced whole
by every refresh.

So it lives in its own small map, keyed by barcode, written by the backfill
that read the export and used by any retailer's search.
"""

import json
from pathlib import Path

from agentcli import UsageError

from pantry.jsonfmt import dumps
from pantry.store import write_atomic

DIET_NAME = "openfoodfacts.diet.json"

# What the export can conclude. Anything else is unknown, and unknown is
# absent rather than a fourth value: a filter must not pass what it cannot
# check.
DIETS = ("vegan", "vegetarian", "non-vegetarian")

# Which of them satisfy a request for vegetarian food.
MEATLESS = frozenset(("vegan", "vegetarian"))


def diet_path(store: Path) -> Path:
    """Where the barcode-to-diet map lives."""
    return store / DIET_NAME


def write_diets(
    path: Path, diets: dict[str, str], write=write_atomic
) -> None:
    """Replace the map with what the export just said."""
    ordered = {code: diets[code] for code in sorted(diets)}
    write(path, dumps(ordered) + "\n")


def read_diets(path: Path) -> dict[str, str]:
    """The map, or an empty one.

    A missing file is not an error: a catalogue can be searched before any
    backfill has run, and every row is simply unknown until one has.
    """
    if not path.is_file():
        return {}

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"could not read {path}: {exc}") from None

    if not isinstance(loaded, dict):
        raise UsageError(f"{path} must contain a JSON object")

    return {str(code): str(value) for code, value in loaded.items()}
