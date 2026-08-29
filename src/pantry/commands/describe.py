"""The human-readable line. Agents read `--json`; this is for a person."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

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

    return f"{identity:<20} {macros:<28} {_cost(product)}{title}"


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
