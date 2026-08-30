"""Umall: a live price search, and no nutrition of its own.

The store publishes no panel anywhere, and its search endpoint publishes no
barcode either — only a title, a price and a product URL. So this provider is
a price finder: it says what Umall sells for a name and what it costs, ranked
the same way every other source is, and carries no panel and no acquirable
reference. A row's nutrition, if it is ever wanted, is a separate `add`.

The suggest endpoint is the network act, so a search costs one request and
answers only under `--source umall`. The transport is injected, so every test
here runs offline.
"""

import json
import re
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from pantry.local import Local
from pantry.open_food_facts import RemoteFailure
from pantry.providers import Provider
from pantry.umall import (
    STORE_URL,
    _decimal,
    is_external_gtin,
    is_food,
    net_grams,
    price_per_100_grams,
)

RETAILER = "umall"

# The store's public search-as-you-type endpoint. It ranks by relevance and
# returns at most ten products, whatever limit is asked for.
SUGGEST_URL = f"{STORE_URL}/search/suggest.json"
_MAX_SUGGEST = 10

# The prices are Australian dollars; the endpoint states no currency code.
_CURRENCY = "AUD"

_USER_AGENT = "pantry/0.1 (https://github.com/mealtime-tools/pantry)"

# A pack size at either edge is not the food's name. Leaving a trailing size
# makes it the head word under the retail-name convention used by `Local`.
_PACK_SIZE = re.compile(
    r"(?:\d+\s*[x×]\s*)?\d+(?:\.\d+)?\s*(?:kg|g|ml|l)\b",
    re.IGNORECASE,
)

# A transport: one URL in, the response body out. Injected so tests run with
# no network, exactly as the retailer page loader is.
Fetch = Callable[[str], str]


def _get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def _url(query: str, limit: int) -> str:
    """The suggest request for one query, brackets percent-encoded.

    `urlencode` encodes the `[` and `]` the endpoint's parameter names carry;
    left raw they are rejected as a malformed query.
    """
    params = urlencode(
        {
            "q": query,
            "resources[type]": "product",
            "resources[limit]": str(min(limit, _MAX_SUGGEST)),
        }
    )
    return f"{SUGGEST_URL}?{params}"


def _absolute(url: str | None) -> str:
    """The product URL as a whole address; the endpoint returns a path."""
    path = str(url or "")
    if path.startswith(("http://", "https://")):
        return path
    return f"{STORE_URL}{path}"


def _search_name(title: str) -> str:
    """The product name without a pack size at either end."""
    size = _PACK_SIZE.search(title)
    if size is None:
        return title.replace(",", " ")

    before = title[: size.start()].strip(" ,-×x")
    after = title[size.end() :].strip(" ,-×x")
    return before or after or title


def _product_json_url(url: str) -> str | None:
    """The public product JSON corresponding to one Umall result URL."""
    parts = urlsplit(url)
    if parts.netloc != urlsplit(STORE_URL).netloc:
        return None
    if not parts.path.startswith("/products/"):
        return None

    path = parts.path if parts.path.endswith(".js") else f"{parts.path}.js"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _barcode_reference(payload: Any) -> str | None:
    """The first manufacturer barcode the product JSON publishes.

    A lead, not a promise: the code is Umall's, and whether any panel source
    holds it is only settled when `pantry add` asks.
    """
    if not isinstance(payload, dict):
        return None

    variants = payload.get("variants")
    if not isinstance(variants, list):
        return None

    for variant in variants:
        if not isinstance(variant, dict):
            continue
        barcode = str(variant.get("barcode") or "")
        if is_external_gtin(barcode):
            return f"barcode:{barcode}"

    return None


def _entry(product: dict[str, Any]) -> dict[str, Any] | None:
    """One suggest product as a search row, or nothing.

    Refused rather than repaired: a non-food category has no panel to ever
    acquire, and a row with no name or no price is not an offer. The suggest
    endpoint publishes no barcode, so there is no `barcode:` reference to set
    and no panel path to point at — the row is shown for its price alone.
    """
    if not is_food(str(product.get("type") or "")):
        return None

    name = str(product.get("title") or "")
    price = _decimal(product.get("price"))
    if not name or price is None:
        return None

    return {
        "id": str(product.get("id") or ""),
        "name": _search_name(name),
        "display_name": name,
        "brand": str(product.get("vendor") or ""),
        "price": price,
        # The title states net content; there is no shipping weight here.
        "pack_grams": net_grams(name),
        "available": bool(product.get("available")),
        "url": _absolute(product.get("url")),
    }


def _result(entry: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
    """One suggest row as a search result: what it is, and what it costs.

    There is no panel, so no nutrient key and no `grams` basis for one beyond
    the pantry default of 100. The price and its per-100 g rate are the whole
    answer, and neither price-per-calorie nor price-per-protein can be given
    without the panel this row does not carry.
    """
    price, pack = entry["price"], entry["pack_grams"]
    name, brand = entry["display_name"], entry["brand"]

    return {
        "id": entry["id"],
        "name": name,
        "title": f"{name} ({brand})" if brand else name,
        "brand": brand,
        "grams": 100,
        "source": RETAILER,
        "price": price,
        "currency": _CURRENCY,
        "pack_grams": pack,
        "price_per_100g": price_per_100_grams(price, pack),
        "available": entry["available"],
        "url": entry["url"],
        "match": match,
    }


class UmallProvider(Provider):
    """Search Umall's live suggest endpoint for prices, and nothing else."""

    name = RETAILER

    searchable = True
    acquirable = False

    def __init__(self, fetch: Fetch | None = None) -> None:
        self._fetch = fetch or _get

    def search(self, query: str, limit: int) -> list[dict]:
        products = self._products(query, limit)
        entries = [row for row in map(_entry, products) if row is not None]

        # Ranked the same way every source is, so one model spans every shop.
        scored = Local(entries).scored(query, limit)
        results = []
        for entry, match in scored:
            result = _result(entry, match)
            reference = self._reference(entry["url"])
            if reference:
                result["ref"] = reference
            results.append(result)

        return results

    def _reference(self, product_url: str) -> str | None:
        """Resolve one optional barcode without sacrificing a price result."""
        url = _product_json_url(product_url)
        if url is None:
            return None

        try:
            return _barcode_reference(json.loads(self._fetch(url)))
        except (OSError, ValueError):
            return None

    def _products(self, query: str, limit: int) -> list[dict]:
        """The suggest endpoint's product list, or the reason there is none."""
        try:
            payload = json.loads(self._fetch(_url(query, limit)))
        except OSError as exc:
            raise RemoteFailure(f"Umall could not be reached: {exc}") from None
        except ValueError:
            raise RemoteFailure("Umall returned a response that is not JSON")

        results = ((payload.get("resources") or {}).get("results")) or {}
        products = results.get("products")
        return products if isinstance(products, list) else []
