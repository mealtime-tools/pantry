"""The human-readable line. Agents read `--json`; this is for a person."""

from typing import Any

_MACROS = (("kcal", "kcal"), ("protein", "p"), ("carbs", "c"), ("fat", "f"))


def _caveat(product: dict[str, Any]) -> str:
    """What the figures are measured against, when the record says.

    Appended rather than columnised: it is free text of any length, and a
    record on a prepared basis must not read like an as-sold one.
    """
    parts = [
        str(product[key])
        for key in ("basis", "basis_note")
        if product.get(key) is not None
    ]
    return f"  [{': '.join(parts)}]" if parts else ""


def describe(product: dict[str, Any]) -> str:
    """One dense line per product, wide enough to identify it."""
    nutrients = product.get("nutrients") or product
    macros = " ".join(
        f"{round(nutrients.get(key) or 0)}{suffix}" for key, suffix in _MACROS
    )

    identity = f"{product.get('source')}:{product.get('id')}"
    title = product.get("title")
    if not title:
        brand = product.get("brand")
        name = product.get("name", "")
        title = f"{name} ({brand})" if brand else name

    return f"{identity:<20} {macros:<28} {title}{_caveat(product)}"
