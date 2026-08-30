"""Reading a Woolworths search, which only a browser can ask for.

The search page is a client-rendered shell: its html carries no products, and
the request behind it is refused at the tls layer for anything that is not a
browser — measured, a plain post returns no response at all. So the products
are read from the page's own request, captured while a real Chrome loads the
ordinary search url.

Headless is refused too, answering "Access Denied", so the window is visible.
Measured 2026-08-30: 4.1s to launch, then 2.0-6.2s a query in the same
session. One session per run, not one per ingredient.

This module holds only the reading, so the parsing is testable with no browser
anywhere near it.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pantry.umall import net_grams, price_per_100_grams

SOURCE = "woolworths"

_CURRENCY = "AUD"

# The ordinary search url, which is what a person would open.
SEARCH_URL = "https://www.woolworths.com.au/shop/search/products?searchTerm={}"

# The request the page makes for its own results.
SEARCH_API = "/apis/ui/Search/products"

# A stockcode is the whole of a Woolworths address: the slug the site adds
# after it is decoration, and the page serves without it. Measured 0.18s.
PRODUCT_URL = "https://www.woolworths.com.au/shop/productdetails/{}"


# Woolworths builds a product name from a template, and where the pack size is
# missing the token survives into the name: stockcode 349163 is published as
# "Quorn Mince NULL". Their defect, but ours to not store. Anchored and
# case-sensitive so a real word is never clipped.
_PLACEHOLDER = re.compile(r"\s+NULL$")


def product_name(value: Any) -> str:
    """The product's name, without a placeholder that failed to substitute."""
    return _PLACEHOLDER.sub("", str(value or "").strip())


def _decimal(value: Any) -> Decimal | None:
    """A stated figure, or nothing. Never a guess."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _product(row: Any) -> dict[str, Any] | None:
    """One search row as a result, or nothing where it is not an offer."""
    if not isinstance(row, dict):
        return None

    # An identity, never a quantity: it arrives as an integer and a barcode
    # that went through a number has already lost its leading zeros.
    stockcode = row.get("Stockcode")
    stockcode = "" if stockcode is None else str(stockcode).strip()

    name = product_name(row.get("Name"))
    price = _decimal(row.get("Price"))
    if not stockcode or not name or price is None:
        return None

    brand = str(row.get("Brand") or "").strip()
    pack = net_grams(str(row.get("PackageSize") or ""))

    result: dict[str, Any] = {
        "id": stockcode,
        "name": name,
        "title": f"{name} ({brand})" if brand else name,
        "brand": brand,
        "grams": 100,
        "source": SOURCE,
        "price": price,
        "currency": _CURRENCY,
        "pack_grams": pack,
        "price_per_100g": price_per_100_grams(price, pack),
        "available": bool(row.get("IsAvailable")),
        # The stockcode is the whole of a product address, so the panel this
        # result has no room for is exactly one `pantry add` away.
        "ref": f"{SOURCE}:{stockcode}",
        "url": PRODUCT_URL.format(stockcode),
    }

    if barcode := str(row.get("Barcode") or "").strip():
        result["barcode"] = barcode

    return result


def read_search(payload: Any, limit: int) -> list[dict[str, Any]]:
    """Every offer the payload holds, in the shop's own order.

    The site groups variants of one product together; the limit counts the
    products a caller would choose between, not the groups around them.

    The order is the shop's and is deliberately left alone. Its relevance
    engine knows its own catalogue and its shoppers' vocabulary, which a word
    match cannot: asked for "bega protein shredded cheese" it answers with
    "Bega Protein Tasty Cheese Grated" second, because it knows those are the
    same thing. Reranking that on shared words dropped it as a weak match and
    left the shelf looking empty. No lexical `match` is attached either, for
    the same reason — it would score the right product badly.
    """
    if not isinstance(payload, dict):
        return []

    groups = payload.get("Products")
    if not isinstance(groups, list):
        return []

    found: list[dict[str, Any]] = []
    for group in groups:
        rows = group.get("Products") if isinstance(group, dict) else None
        for row in rows or ():
            if len(found) >= limit:
                return found
            if (result := _product(row)) is not None:
                found.append(result)

    return found
