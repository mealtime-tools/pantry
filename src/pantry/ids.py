"""Product identifiers are strings, normalized wherever a food enters.

Nothing in the current Coles database forces this: every id there is a plain
integer that `str()` round-trips exactly. The sources that come next do force
it — Open Food Facts ids are EAN/UPC barcodes whose leading zeros are
significant, and hand-written localstore rows have no consistent type at all.
"""

import re
from typing import Any

_DIGITS = re.compile(r"^[0-9]+$")


def normalize_id(value: Any) -> str:
    """Canonicalize an id from any source into its string form."""
    if value is None:
        return ""
    return str(value).strip()


def id_sort_key(value: str) -> tuple[int, int, str]:
    """Order ids deterministically, so a committed shard sorts identically.

    Plain integers compare by magnitude, which for a digit string is length
    first and codepoint second; anything else compares by codepoint alone and
    sorts after the integers. Locale collation is deliberately avoided because
    it varies with the ICU build. Ids differing only by leading zeros stay
    distinct, and stably ordered after the shorter ids they outrank.
    """
    if _DIGITS.match(value):
        return (0, len(value), value)
    return (1, 0, value)
