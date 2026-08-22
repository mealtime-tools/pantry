"""Reading a product off a supermarket page.

Both sites are Next.js applications that server-render their whole product
payload into a `__NEXT_DATA__` script tag, nutrition panel included. That is
the entire reason this fetcher needs no browser: a plain GET with an ordinary
user agent returns the panel, so `browser.py` is a fallback for the day one of
them stops doing that, not the normal path.

Nothing here performs I/O. A page arrives as a string and leaves as a record,
which is what lets every test run offline.
"""

import json
import math
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from nutrition.figures import read_rows

from pantry.ids import normalize_id
from pantry.nutrition import (
    NUTRIENTS,
    nutrients_for_storage,
    parse_amount,
)
from pantry.products import Product

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)

# The column heading Woolworths files its per-100 g figures under.
_WOOLIES_PER_100 = "Quantity Per 100g / 100mL"


class SiteError(ValueError):
    """A url or page this package cannot read."""


@dataclass(frozen=True)
class ProductRef:
    """Which product a url points at, in every spelling of its id."""

    source: str
    id: str
    url: str


def _coles_site_id(path: str) -> str | None:
    """A Coles url ends in the product id: /product/<slug>-<id>."""
    match = re.search(r"/product/.*?-(\d+)/?$", path)
    return match.group(1) if match else None


def _read_coles(payload: Any) -> dict[str, Any]:
    product = (payload or {}).get("product")
    if not product:
        raise SiteError("page carries no product")

    # Coles ships both columns as separate breakdowns; only one is per 100 g.
    nutrition = product.get("nutrition") or {}
    breakdowns = nutrition.get("breakdown") or []
    chosen = next(
        (b for b in breakdowns if "100" in str((b or {}).get("title", ""))),
        None,
    )
    rows = [
        (str(n.get("nutrient", "")), str(n.get("value", "")))
        for n in (chosen or {}).get("nutrients") or []
    ]

    return {
        "name": str(product.get("name") or ""),
        "brand": str(product.get("brand") or ""),
        "panel": read_rows(rows),
        "serving": nutrition.get("servingSize"),
        "total": product.get("size"),
    }


def _woolworths_site_id(path: str) -> str | None:
    """A Woolworths url leads with the stockcode: /shop/productdetails/<id>."""
    match = re.search(r"/shop/productdetails/(\d+)", path)
    return match.group(1) if match else None


def _read_woolworths(payload: Any) -> dict[str, Any]:
    details = (payload or {}).get("pdDetails") or {}
    product = details.get("Product")
    if not product:
        raise SiteError("page carries no product")

    information = details.get("NutritionalInformation") or []
    rows = [
        (
            str(n.get("Name") or ""),
            str((n.get("Values") or {}).get(_WOOLIES_PER_100) or ""),
        )
        for n in information
    ]

    return {
        "name": str(product.get("Name") or ""),
        "brand": str(product.get("Brand") or ""),
        "panel": read_rows(rows),
        "serving": information[0].get("ServingSize") if information else None,
        "total": product.get("PackageSize"),
    }


_SITES = {
    "coles": (("coles.com.au",), _coles_site_id, _read_coles),
    "woolworths": (
        ("woolworths.com.au",),
        _woolworths_site_id,
        _read_woolworths,
    ),
}


def product_ref(url: str) -> ProductRef:
    """Resolve a url into the product it names.

    Raises rather than returning nothing, because every caller is about to
    spend a page load and the message is what redirects the user to `add`.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise SiteError(f"not a url: {url}")

    host = parts.hostname or ""
    bare = host.removeprefix("www.")
    source = next((s for s, (h, *_) in _SITES.items() if bare in h), None)
    if source is None:
        raise SiteError(
            f"no reader for {host}; add it with `pantry add --manual`"
        )

    site_id = _SITES[source][1](parts.path)
    if not site_id:
        raise SiteError(f"{url} does not name a product page")

    return ProductRef(source=source, id=normalize_id(site_id), url=url)


def _next_data(html: str) -> Any:
    """Pull the server-rendered payload out of a page, or say it was absent."""
    match = _NEXT_DATA.search(html)
    if not match:
        raise SiteError("page carries no __NEXT_DATA__ payload")

    try:
        payload = json.loads(match.group(1))
    except ValueError as cause:
        raise SiteError(
            "page __NEXT_DATA__ payload is not valid JSON"
        ) from cause

    return (payload or {}).get("props", {}).get("pageProps")


def parse_product_page(
    ref: ProductRef, html: str, zero_calorie: bool = False
) -> Product:
    """Read a fetched page into a record in exactly the JSONL schema.

    Raises if the panel is missing or implausible unless the caller explicitly
    declares a zero-calorie product. That refusal is what distinguishes a
    genuine zero from a block page or a discontinued product.
    """
    if ref.source not in _SITES:
        raise SiteError(f"no reader for source {ref.source}")

    page = _SITES[ref.source][2](_next_data(html))
    if not page["name"]:
        raise SiteError(f"{ref.url}: page carries no product name")

    # The panel is validated before anything is built from it, so a bad page
    # fails with the reason rather than producing a record nobody can trust.
    panel = nutrients_for_storage(page["panel"], zero_calorie)

    serving_size, serving_unit = parse_amount(page["serving"])
    total_size, total_unit = parse_amount(page["total"])

    return build_record(
        source=ref.source,
        product_id=ref.id,
        name=page["name"],
        brand=page["brand"],
        panel=panel,
        url=ref.url,
        serving=(serving_size, serving_unit),
        total=(total_size, total_unit),
    )


def build_record(
    *,
    source: str,
    product_id: str,
    name: str,
    brand: str,
    panel: dict[str, float],
    url: str | None = None,
    serving: tuple[float | None, str | None] = (None, None),
    total: tuple[float | None, str | None] = (None, None),
    basis: str | None = None,
    basis_note: str | None = None,
) -> Product:
    """Assemble a record, omitting every field the label did not supply."""
    optional = {
        # Present only when the label printed kilojoules; never derived back.
        "kj": panel.get("kj"),
        **{key: panel.get(key) for key in NUTRIENTS},
        # Absent unless a caller declares one: an unmarked record is as-sold.
        "basis": basis,
        "basis_note": basis_note,
        "url": url,
        "serving_size": serving[0],
        "serving_unit": serving[1],
        "total_size": total[0],
        "total_unit": total[1],
    }

    record: Product = {
        "source": source,
        "id": product_id,
        "name": name,
        "brand": brand,
        "fat": panel["fat"],
        "carbohydrates": panel["carbohydrates"],
        "protein": panel["protein"],
        # One decimal is what the database is written with. Rounded half-up
        # rather than by `round`, whose banker's rounding would disagree with
        # the JavaScript that wrote the frozen shards.
        "kcal": math.floor(panel["kcal"] * 10 + 0.5) / 10,
    }
    record.update({k: v for k, v in optional.items() if v is not None})

    return record
