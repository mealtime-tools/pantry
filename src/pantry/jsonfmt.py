"""JSON in the exact bytes JavaScript would have written.

`data/coles.jsonl` cannot be regenerated, so every writer of a product record
has to reproduce the serializer that made it. Python's `json` module differs
from `JSON.stringify` in one measurable place: `repr(0.00001)` is `1e-05` while
ECMAScript renders `0.00001`. Real row 8520 of `coles.jsonl` carries
`"fiber":0.00001`, so using `json.dumps` there would rewrite the file.

A figure arrives as a `Decimal`, which already carries the digits and the
exponent this format is written in terms of, so nothing has to be recovered
from a `repr`. `json.dumps` cannot write one at all, which is the second
reason this module exists.

There is deliberately no float branch. A float has no decimal digits of its
own, so writing one means guessing which it meant; refusing it makes the noise
this format keeps out a `TypeError` instead of a silently rewritten shard.
"""

import json
from decimal import Decimal
from typing import Any

# Where ECMAScript leaves positional notation, and Python's `repr` does not.
_EXPONENTIAL_AT = 21

Number = Decimal | int


def _digits(value: Decimal) -> tuple[str, int]:
    """Split a decimal into its significant digits and decimal exponent."""
    _, digits, exponent = value.as_tuple()
    combined = "".join(str(digit) for digit in digits)

    # `point` is what the ECMAScript algorithm calls `n`: digits left of it.
    point = len(combined) + int(exponent)

    # Leading zeros are not significant; each dropped moves the point left.
    stripped = combined.lstrip("0")
    point -= len(combined) - len(stripped)

    return stripped.rstrip("0") or "0", point


def _exponential(digits: str, point: int) -> str:
    """Render as ECMAScript does: a digit, the rest, a signed exponent."""
    head = digits[0] if len(digits) == 1 else f"{digits[0]}.{digits[1:]}"
    exponent = point - 1
    return f"{head}e{'+' if exponent >= 0 else '-'}{abs(exponent)}"


def format_number(value: Number) -> str:
    """Format a number exactly as `JSON.stringify` would.

    ECMAScript reaches for exponential notation only when the decimal exponent
    is below -6 or at least 21; Python's `repr` switches at 1e-4 and 1e+16.
    Integral values carry no `.0` either: 239.0 is written `239`.
    """
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, Decimal):
        raise TypeError(f"cannot serialize {type(value).__name__} as JSON")

    if not value.is_finite():
        raise ValueError(f"cannot serialize {value} as JSON")
    integral = value == value.to_integral_value()
    if integral and abs(value) < 10**_EXPONENTIAL_AT:
        return str(int(value))

    sign = "-" if value < 0 else ""
    digits, point = _digits(abs(value))

    # The three positional forms, then exponential for everything beyond them.
    if len(digits) <= point <= _EXPONENTIAL_AT:
        return f"{sign}{digits}{'0' * (point - len(digits))}"
    if 0 < point <= _EXPONENTIAL_AT:
        return f"{sign}{digits[:point]}.{digits[point:]}"
    if -6 < point <= 0:
        return f"{sign}0.{'0' * -point}{digits}"

    return f"{sign}{_exponential(digits, point)}"


def dumps(value: Any) -> str:
    """Serialize a record the way JavaScript would, with no spaces.

    Written out by hand because Python's encoder offers no hook for number
    formatting, and the number formatting is the entire point.
    """
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, Decimal)):
        return format_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(dumps(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = (f"{dumps(str(k))}:{dumps(v)}" for k, v in value.items())
        return "{" + ",".join(pairs) + "}"

    raise TypeError(f"cannot serialize {type(value).__name__} as JSON")
