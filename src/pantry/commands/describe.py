"""The human-readable line. Agents read `--json`; this is for a person."""

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

    return f"{identity:<20} {macros:<28} {title}"
