"""Umall: a searchable retail catalogue, and no nutrition of its own.

The store publishes no panel anywhere — not in the product description, not
in a metafield, not on the page. What it does publish is a barcode, and for
roughly seven rows in ten that barcode identifies the product outside Umall,
so the panel is whatever `off:<barcode>` already holds. This provider joins
the two and prices the result; it never invents a figure for a row the join
missed.

Searching is free because it reads the catalogue on disk. Building that
catalogue is the network act, and it is a separate command.
"""

import json
import urllib.request
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

from pantry.catalog import read_catalog
from pantry.local import Local
from pantry.open_food_facts import RemoteFailure
from pantry.products import NUTRIENT_KEYS
from pantry.providers import Provider
from pantry.store import Store
from pantry.umall import (
    STORE_URL,
    price_per_100_grams,
    price_per_100_kcal,
    price_per_gram,
)

RETAILER = "umall"

# The theme publishes this to its own front end, so it is a public read
# credential rather than a secret. It can be rotated by the store at any time,
# which is a refresh that fails with a clear message, not a wrong answer.
API_URL = f"{STORE_URL}/api/2025-01/graphql.json"
STOREFRONT_TOKEN = "4e76a97e8099941b661db168fc662268"

# The most a Storefront connection returns at once.
_PAGE_SIZE = 250

# Shopify refuses to page past this many items in one connection, and Umall
# lists more products than that. So a sweep is several connections: page until
# the cap is near, then start again from the last product's creation time.
_PAGINATION_CAP = 25000
_WINDOW = _PAGINATION_CAP - _PAGE_SIZE

# Sorted by creation so a window has a boundary to resume from, and `createdAt`
# is selected because that boundary is read off the last node. `barcode` is the
# reason this is GraphQL at all: `/products.json` is simpler and omits it.
_QUERY = """
query Catalogue($cursor: String, $size: Int!, $query: String) {
  products(first: $size, after: $cursor, query: $query,
           sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      handle title vendor productType tags createdAt
      variants(first: 1) {
        nodes {
          sku barcode weight weightUnit availableForSale
          price { amount currencyCode }
        }
      }
    }
  }
}
"""

# Quoted on purpose: unquoted, Shopify parses the timestamp loosely and
# returns products created before the bound, so a window would not advance.
_SINCE = 'created_at:>="{}"'

_USER_AGENT = "pantry/0.1 (https://github.com/mealtime-tools/pantry)"

Fetch = Callable[[str, bytes, dict[str, str]], bytes]


def _post(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, body, headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


class Storefront:
    """The whole catalogue, one cursor-paged query at a time."""

    def __init__(self, fetch: Fetch | None = None) -> None:
        self._fetch = fetch or _post

    def _page(self, cursor: str | None, query: str | None) -> dict[str, Any]:
        """One page, or the reason there is not one.

        A GraphQL error is reported rather than retried: the two that happen
        are a rotated token and a removed API version, and neither is fixed by
        asking again.
        """
        body = json.dumps(
            {
                "query": _QUERY,
                "variables": {
                    "cursor": cursor,
                    "size": _PAGE_SIZE,
                    "query": query,
                },
            }
        ).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Storefront-Access-Token": STOREFRONT_TOKEN,
            "User-Agent": _USER_AGENT,
        }

        try:
            payload = json.loads(self._fetch(API_URL, body, headers))
        except OSError as exc:
            raise RemoteFailure(f"Umall could not be reached: {exc}") from None
        except ValueError:
            raise RemoteFailure("Umall returned a response that is not JSON")

        if payload.get("errors"):
            first = payload["errors"][0].get("message", "unknown error")
            raise RemoteFailure(f"Umall refused the catalogue query: {first}")

        products = (payload.get("data") or {}).get("products")
        if not isinstance(products, dict):
            raise RemoteFailure("Umall returned no catalogue")

        return products

    def _window(self, since: str | None) -> Iterator[dict[str, Any]]:
        """One connection's worth, stopping short of the pagination cap."""
        cursor: str | None = None
        taken = 0
        query = _SINCE.format(since) if since else None

        while taken < _WINDOW:
            page = self._page(cursor, query)
            nodes = page.get("nodes") or []
            yield from nodes
            taken += len(nodes)

            info = page.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                return
            cursor = info.get("endCursor")

    def sweep(self) -> Iterator[dict[str, Any]]:
        """Every product the store lists, across as many windows as it takes.

        Windows overlap at their boundary, because several products can share
        one creation second and excluding that second would drop them. So the
        products already seen are tracked, and a window that yields none of
        them ends the sweep — including the pathological one where more than a
        cap's worth share a single timestamp and no boundary can advance.
        """
        seen: set[str] = set()
        since: str | None = None

        while True:
            fresh = 0
            boundary: str | None = None

            for node in self._window(since):
                boundary = node.get("createdAt") or boundary
                handle = str(node.get("handle") or "")
                if handle in seen:
                    continue

                seen.add(handle)
                fresh += 1
                yield node

            if not fresh or boundary is None:
                return
            since = boundary


def _panel(store: Store, entry: dict[str, Any]) -> dict[str, Any]:
    """The nutrition already held for this barcode, if any is.

    Only an external barcode is looked up. An in-store code would collide with
    whatever manufacturer's product happens to share those digits, which is a
    wrong panel rather than a missing one.
    """
    reference = entry.get("ref")
    if not reference:
        return {}

    held = store.find("openfoodfacts", reference.removeprefix("off:"))
    if held is None:
        return {}

    return {
        key: held[key] for key in NUTRIENT_KEYS if held.get(key) is not None
    }


def _priced(
    entry: dict[str, Any], panel: dict[str, Any], fetched_at: str
) -> dict[str, Any]:
    """One catalogue row as a search result: what it is, and what it costs.

    Nutrients are per 100 g, as every pantry result is, so `grams` says 100
    and the pack weight keeps its own key. The unit prices are the reason the
    two are carried together: neither half states what a gram of protein cost.
    """
    price: Decimal | None = entry.get("price")
    pack: Decimal | None = entry.get("pack_grams")
    name, brand = entry["name"], entry.get("brand", "")

    result: dict[str, Any] = {
        "id": entry["id"],
        "name": name,
        "title": f"{name} ({brand})" if brand else name,
        "brand": brand,
        **panel,
        "grams": 100,
        "source": RETAILER,
        "price": price,
        "currency": entry.get("currency"),
        "pack_grams": pack,
        "price_per_100g": price_per_100_grams(price, pack),
        "price_per_100kcal": price_per_100_kcal(
            price, pack, panel.get("kcal")
        ),
        "price_per_g_protein": price_per_gram(
            price, pack, panel.get("protein")
        ),
        # Stamped per row: a price is only true as of the sweep that read it.
        "price_at": fetched_at,
        "available": entry.get("available"),
        "url": entry.get("url"),
    }

    # Where the panel would come from, so an agent can go and acquire it.
    if entry.get("ref"):
        result["ref"] = entry["ref"]

    return result


class UmallProvider(Provider):
    """Search a refreshed Umall catalogue, priced against held nutrition."""

    name = RETAILER

    searchable = True
    acquirable = False

    # Reads a file, so it costs nothing and answers without `--remote`.
    remote = False

    def __init__(self, store: Store, path: Path) -> None:
        self._store = store
        self._path = path

    @property
    def enabled(self) -> bool:
        """False until a catalogue exists.

        A clone that has never refreshed drops out of the fan-out silently,
        exactly as an unconfigured provider does, rather than failing every
        search with a message about a file the user never asked for.
        """
        return self._path.is_file()

    def search(self, query: str, limit: int) -> list[dict]:
        document = read_catalog(self._path)
        entries = document["products"]
        fetched_at = document["fetched_at"]

        return [
            _priced(entry, _panel(self._store, entry), fetched_at)
            for entry in Local(entries).ranked(query, limit)
        ]
