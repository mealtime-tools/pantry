"""JSON in the exact bytes JavaScript would have written.

`data/coles.jsonl` cannot be regenerated, so every writer of a product record
has to reproduce the serializer that made it. Python's `json` module differs
from `JSON.stringify` in one measurable place: `repr(0.00001)` is `1e-05` while
ECMAScript renders `0.00001`. Real row 8520 of `coles.jsonl` carries
`"fiber":0.00001`, so using `json.dumps` there would rewrite the file.
"""

import json
import math
from typing import Any


def _digits(value: float) -> tuple[str, int]:
    """Split a float into its shortest digit string and decimal exponent.

    `repr` already yields the shortest round-tripping digits, which is the
    same set ECMAScript's `Number::toString` is defined over; only the
    placement of the decimal point has to be redone.
    """
    text = repr(value)
    mantissa, _, exponent = text.partition("e")
    integral, _, fractional = mantissa.partition(".")

    # `point` counts digits to the left of the decimal separator, which is what
    # the ECMAScript algorithm calls `n`.
    combined = integral + fractional
    point = len(integral) + int(exponent or 0)

    # Leading zeros are not significant digits; each one dropped moves the
    # decimal point left by one place.
    stripped = combined.lstrip("0")
    point -= len(combined) - len(stripped)

    return stripped.rstrip("0") or "0", point


def _exponential(digits: str, point: int) -> str:
    """Render as ECMAScript does: a digit, the rest, a signed exponent."""
    head = digits[0] if len(digits) == 1 else f"{digits[0]}.{digits[1:]}"
    exponent = point - 1
    return f"{head}e{'+' if exponent >= 0 else '-'}{abs(exponent)}"


def format_number(value: float) -> str:
    """Format a number exactly as `JSON.stringify` would.

    ECMAScript reaches for exponential notation only when the decimal exponent
    is below -6 or at least 21; Python's `repr` switches at 1e-4 and 1e+16.
    Integral values carry no `.0` either: 239.0 is written `239`.
    """
    if isinstance(value, int) or value.is_integer() and abs(value) < 1e21:
        return str(int(value))
    if not math.isfinite(value):
        raise ValueError(f"cannot serialize {value} as JSON")

    sign = "-" if value < 0 else ""
    digits, point = _digits(abs(value))

    # The three positional forms, then exponential for everything beyond them.
    if len(digits) <= point <= 21:
        return f"{sign}{digits}{'0' * (point - len(digits))}"
    if 0 < point <= 21:
        return f"{sign}{digits[:point]}.{digits[point:]}"
    if -6 < point <= 0:
        return f"{sign}0.{'0' * -point}{digits}"

    return f"{sign}{_exponential(digits, point)}"


def dumps(value: Any) -> str:
    """Serialize a record the way JavaScript would, with no spaces.

    Written out by hand because Python's encoder offers no hook for float
    formatting, and the float formatting is the entire point.
    """
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return format_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(dumps(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = (f"{dumps(str(k))}:{dumps(v)}" for k, v in value.items())
        return "{" + ",".join(pairs) + "}"

    raise TypeError(f"cannot serialize {type(value).__name__} as JSON")
