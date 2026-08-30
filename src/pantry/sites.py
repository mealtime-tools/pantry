"""Reading a product off a supermarket page.

Both sites server-render their whole product payload, nutrition panel included,
into a `__NEXT_DATA__` script tag, so a plain GET with an ordinary user agent
returns the panel and `browser.py` is only a fallback. Nothing here performs
I/O: a page arrives as a string and leaves as a record, so every test runs
offline.
"""

import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import urlsplit

from pantry.ids import normalize_id
from pantry.nutrition import nutrients_for_storage, panel_from_rows
from pantry.products import (
    BASIS_GRAMS,
    MILLILITRE_NOTE,
    UNSTATED_UNIT_NOTE,
    Figure,
    Product,
    as_decimal,
)
from pantry.woolworths import product_name

# The one decimal place every shard states energy to.
_ENERGY_PLACE = Decimal("0.1")

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)

# The column heading Woolworths files its per-100 g figures under.
_WOOLIES_PER_100 = "Quantity Per 100g / 100mL"

# A Coles liquid's column, and nothing else: a qualifier means it is not one.
_PER_100_ML = re.compile(r"^\s*(?:per\s*)?100\s*ml\s*$", re.IGNORECASE)

# One column headed for grams and millilitres alike, which states neither.
_PER_100_BOTH = re.compile(
    r"^\s*(?:per\s*)?100\s*g\s*/\s*ml\s*$", re.IGNORECASE
)


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
    title = str((chosen or {}).get("title", ""))
    rows = [
        (str(n.get("nutrient", "")), str(n.get("value", "")))
        for n in (chosen or {}).get("nutrients") or []
    ]

    return {
        "name": str(product.get("name") or ""),
        "brand": str(product.get("brand") or ""),
        "barcode": str(product.get("gtin") or "") or None,
        "panel": panel_from_rows(rows),
        "basis_note": _coles_basis(title),
    }


def _coles_basis(title: str) -> str | None:
    """What the column heading says the figures are measured against.

    Coles titles this `Per 100g/ml`, one column serving both units, so the
    page states neither. Confirmed against a live page on 2026-08-30; the
    older `Per 100mL` heading is still read, since the shards hold rows from
    when it was written that way.
    """
    if _PER_100_BOTH.match(title):
        return UNSTATED_UNIT_NOTE
    return MILLILITRE_NOTE if _PER_100_ML.match(title) else None


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
        "name": product_name(product.get("Name")),
        "brand": str(product.get("Brand") or ""),
        "barcode": str(product.get("Barcode") or "") or None,
        "panel": panel_from_rows(rows),
        # One column for both units, so the page states neither.
        "basis_note": UNSTATED_UNIT_NOTE,
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
            f"no reader for {host}; add it with `pantry add --input -`"
        )

    site_id = _SITES[source][1](parts.path)
    if not site_id:
        raise SiteError(f"{url} does not name a product page")

    return ProductRef(source=source, id=normalize_id(site_id), url=url)


def next_data(html: str) -> Any:
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


def parse_product_page(ref: ProductRef, html: str) -> Product:
    """Read a fetched page into a record in exactly the JSONL schema."""
    return read_product(ref, next_data(html))


def read_product(ref: ProductRef, payload: Any) -> Product:
    """Read a page's own payload into a record in the JSONL schema.

    Split from the html so the payload is the unit under test, and so a route
    that serves the same object without a page around it can be read as is.
    Missing nutrients stay missing; reported values are validated.
    """
    if ref.source not in _SITES:
        raise SiteError(f"no reader for source {ref.source}")

    page = _SITES[ref.source][2](payload)
    if not page["name"]:
        raise SiteError(f"{ref.url}: page carries no product name")

    # Validated first, so a bad page fails with a reason, not a bad record.
    panel = nutrients_for_storage(page["panel"])
    return build_record(
        source=ref.source,
        product_id=ref.id,
        name=page["name"],
        brand=page["brand"],
        panel=panel,
        url=ref.url,
        barcode=page.get("barcode"),
        # No `basis`: no retailer page declares one, and absent means it.
        basis_note=page["basis_note"],
    )


def build_record(
    *,
    source: str,
    product_id: str,
    name: str,
    brand: str,
    panel: dict[str, Figure],
    url: str | None = None,
    barcode: str | None = None,
    basis: str | None = None,
    basis_note: str | None = None,
) -> Product:
    """Assemble a per-100 g record, omitting every field the label omits."""
    optional = {
        # Absent unless a caller declares one: an unmarked record is as-sold.
        "basis": basis,
        "basis_note": basis_note,
        "url": url,
        "barcode": barcode,
    }

    record: Product = {
        "source": source,
        "id": product_id,
        "name": name,
        "brand": brand,
    }
    nutrients = {
        key: value for key, value in panel.items() if value is not None
    }
    if panel.get("kcal") is not None:
        # Half-up, as the historical shard was written; `round` is half-even.
        nutrients["kcal"] = as_decimal(panel["kcal"]).quantize(
            _ENERGY_PLACE, rounding=ROUND_HALF_UP
        )
    record.update(nutrients)
    record.update({k: v for k, v in optional.items() if v is not None})
    record["grams"] = BASIS_GRAMS

    return record
