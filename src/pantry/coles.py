"""Reading a Coles search, which a plain request is enough to ask for.

Unlike Woolworths, the search page is server-rendered: its `__NEXT_DATA__`
carries the whole result set, so no browser and no window are involved.
Measured 2026-08-30, one request.

It costs one of the four or five page loads Coles allows in a burst, which is
why a search here is one request and never a walk through pages.

This module holds only the reading, so the parsing is testable with no network
anywhere near it.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pantry.umall import net_grams, price_per_100_grams

SOURCE = "coles"

_CURRENCY = "AUD"

# The ordinary search url, which is what a person would open.
SEARCH_URL = "https://www.coles.com.au/search/products?q={}"

_PRODUCT_URL = "https://www.coles.com.au/product/{}"

# The rows worth showing. The same list carries ad tiles and banners.
_PRODUCT_TYPE = "PRODUCT"

# Everything that is not a word or a number becomes a separator, and runs of
# separators collapse: "Cheese & Crackers" is `cheese-crackers`, not
# `cheese---crackers`.
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def _decimal(value: Any) -> Decimal | None:
    """A stated figure, or nothing. Never a guess."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def product_url(product_id: str, brand: str, name: str, size: str) -> str:
    """The address Coles prints for this product.

    A search row states the id and the three parts the slug is built from
    but not the address itself, so it is rebuilt here: brand, name, size,
    id. Verified 2026-08-30 by acquiring two rebuilt addresses, one with
    punctuation in its name; both served their panel.
    """
    slug = _NOT_SLUG.sub("-", f"{brand} {name} {size}".lower()).strip("-")
    return _PRODUCT_URL.format(f"{slug}-{product_id}" if slug else product_id)


def _product(row: Any) -> dict[str, Any] | None:
    """One search row as a result, or nothing where it is not an offer."""
    if not isinstance(row, dict) or row.get("_type") != _PRODUCT_TYPE:
        return None

    # An identity, never a quantity, for the same reason a barcode is a string.
    product_id = row.get("id")
    product_id = "" if product_id is None else str(product_id).strip()

    name = str(row.get("name") or "").strip()
    pricing = (
        row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
    )
    price = _decimal(pricing.get("now"))
    if not product_id or not name or price is None:
        return None

    brand = str(row.get("brand") or "").strip()
    size = str(row.get("size") or "").strip()
    pack = net_grams(size)
    url = product_url(product_id, brand, name, size)

    return {
        "id": product_id,
        "name": name,
        "title": f"{name} ({brand})" if brand else name,
        "brand": brand,
        "grams": 100,
        "source": SOURCE,
        "price": price,
        "currency": _CURRENCY,
        "pack_grams": pack,
        "price_per_100g": price_per_100_grams(price, pack),
        "available": bool(row.get("availability")),
        # The panel this result has no room for is one `pantry add` away.
        "ref": f"{SOURCE}:{url}",
        "url": url,
    }


def read_search(payload: Any, limit: int) -> list[dict[str, Any]]:
    """Every offer the payload holds, in the shop's own order.

    The order is the shop's and is deliberately left alone, for the reason set
    out in `woolworths.read_search`: its relevance engine knows its catalogue
    and its shoppers' words, and rescoring on shared words drops right answers.
    No lexical `match` is attached either.
    """
    results = (payload or {}).get("searchResults") if payload else None
    rows = results.get("results") if isinstance(results, dict) else None
    if not isinstance(rows, list):
        return []

    found: list[dict[str, Any]] = []
    for row in rows:
        if len(found) >= limit:
            break
        if (result := _product(row)) is not None:
            found.append(result)

    return found
