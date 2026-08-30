"""The human-readable line. Agents read `--json`; this is for a person."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pantry.local import WEAK_MATCH

_MACROS = (("kcal", "kcal"), ("protein", "p"), ("carbs", "c"), ("fat", "f"))


def describe(product: dict[str, Any]) -> str:
    """One dense line per product, wide enough to identify it."""
    macros = " ".join(
        f"{round(value) if value is not None else '?'}{suffix}"
        for key, suffix in _MACROS
        for value in (product.get(key),)
    )

    identity = f"{product.get('source')}:{product.get('id')}"
    title = product.get("title")
    if not title:
        brand = product.get("brand")
        name = product.get("name", "")
        title = f"{name} ({brand})" if brand else name

    body = f"{_cost(product)}{title}{_weak(product)}{_entered(product)}"
    return f"{identity:<20} {macros:<28} {body}"


def _entered(product: dict[str, Any]) -> str:
    """Say when the figures were keyed in rather than read from the source.

    Same reason as `~weak`: an unmarked line reads as something the tool
    fetched, and under a retailer identity that is exactly the wrong thing to
    assume.
    """
    return "  ~entered" if product.get("entered") else ""


def _weak(product: dict[str, Any]) -> str:
    """Say so when the best answer is not the thing that was asked for.

    An agent reads `match` from `--json`; a person reads a line, and an
    unmarked line reads as confident whatever the record actually is.
    """
    match = product.get("match")
    if match is None or match.get("score") is None:
        return ""

    return "  ~weak" if match["score"] < WEAK_MATCH else ""


def _cost(product: dict[str, Any]) -> str:
    """What the pack costs, for the sources that state it.

    Empty for every source that does not, so the line is unchanged for them.
    Without this a priced result reads exactly like an unpriced one, and the
    price is the only thing the retailer knew that the panel did not.
    """
    price = product.get("price")
    if price is None:
        return ""

    unit = product.get("price_per_100g")
    # Rounded for the eye only. The payload keeps every place a division
    # produced, because that is what a ranking by unit price sorts on.
    per_100 = f" ({_cents(unit)}/100g)" if unit is not None else ""

    return f"${_cents(price)}{per_100}  "


def _cents(value: Any) -> str:
    """Money as money: two places, however many the division produced."""
    return f"{Decimal(value).quantize(Decimal('0.01'), ROUND_HALF_UP)}"
