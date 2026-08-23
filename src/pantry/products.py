"""The record format: what a product is, and how it is read and written.

`grams` is the weight a record's nutrients describe. Every stored record is per
100 g and every one states it, so storage and the wire are one shape. There is
no pack size or serving size. A per-100 mL panel is stored as per 100 g,
unconverted, and says so in `basis_note`.

Structural fields are enumerated because each is validated in its own way.
Energy and the four macros are enumerated because they are cross-checked
against each other. Every other nutrient is open, governed by the vocabulary
in `pantry.nutrition`.
"""

import json
import math
from typing import Any

from pantry.ids import id_sort_key
from pantry.jsonfmt import dumps
from pantry.nutrition import NUTRIENTS

# The data owners. `localstore` is deliberately absent: it is a storage
# layer, and
# this tuple's order is also the order shards are written in.
PRODUCT_SOURCES = (
    "coles",
    "woolworths",
    "afcd",
    "usda",
    "openfoodfacts",
    "manual",
)

# What a record's nutrients are measured against. Absent is the default and
# means as-sold: the frozen shards predate the key, and writing a default into
# them would rewrite a file nothing can regenerate.
PRODUCT_BASES = (
    "as_sold",
    "as_prepared",
)

# What identifies and packages a product, in the order these are written. The
# scrape emitted several key orders and no particular record order, which
# turned an edit to one product into a diff across the whole file. Pinning
# both is the entire point of storing JSONL.
PRODUCT_KEYS = (
    "source",
    "id",
    "name",
    "brand",
    "url",
    "grams",
)

# Every stored nutrient is a top-level key, in this order.
NUTRIENT_KEYS = ("kcal", "kj", "protein", "fat", "carbs", *NUTRIENTS)

# Written last, after the figures they qualify, so a line read by eye carries
# the caveat beside the numbers it applies to.
BASIS_KEYS = ("basis", "basis_note")

# What a record says when its panel was printed per 100 mL, exact for water.
MILLILITRE_NOTE = "per 100 mL, read as 100 g"

# The same, where one column is headed for both units and so states neither.
UNSTATED_UNIT_NOTE = "per 100 g or 100 mL; the page does not say which"

Product = dict[str, Any]

# The basis every stored record holds, and what absence means on a frozen row.
BASIS_GRAMS = 100

# Grams per 100 g, so 100 is the ceiling for every nutrient alike. Pure table
# salt is only 38.758 g of sodium, so nothing edible comes near it.
_MAX_PER_100G = 100

# Where a restated figure is rounded, the precision every source is read to.
_PLACES = 6

# Every key a record may hold. Closed rather than open: an unrecognised key is
# a misspelling far more often than it is a new field, and `sodum` would store
# cleanly and then no consumer would ever find the sodium again.
_ALLOWED_KEYS = frozenset((*PRODUCT_KEYS, *NUTRIENT_KEYS, *BASIS_KEYS))


class ProductError(ValueError):
    """A record that would need a compatibility guess to accept."""


def _restated(key: str, value: Any, factor: float) -> Any:
    """One figure against a new basis, unchanged when unknown or not moving."""
    if value is None or factor == 1:
        return value

    moved = value * factor
    # Neither JSON nor this package's own serializer can express one of these.
    if not math.isfinite(moved):
        raise ProductError(f"{key} does not survive that weight: {moved}")

    restated = round(moved, _PLACES)
    # Zero is reserved for a figure the source itself reported as zero.
    if restated == 0 and value != 0:
        raise ProductError(f"that weight rounds {key} away to zero")
    return restated


def restate(
    nutrients: dict[str, Any], frm: float | None, to: float | None = None
) -> dict[str, Any]:
    """Every nutrient moved from one weight to another, `kj` included."""
    # Zero or absent reads as 100 rather than being divided by.
    factor = (to or BASIS_GRAMS) / (frm or BASIS_GRAMS)
    return {
        key: _restated(key, value, factor) if key in NUTRIENT_KEYS else value
        for key, value in nutrients.items()
    }


def rescale(product: Product, grams: float | None = None) -> Product:
    """A record stated against `grams`, or per 100 g, always saying which."""
    return {
        **restate(product, product.get("grams"), grams),
        "grams": grams or BASIS_GRAMS,
    }


def identity(product: Product) -> tuple[str, str]:
    """The only meaningful name for a product: neither half stands alone."""
    return (str(product.get("source")), str(product.get("id")))


def assert_identity(product: Product) -> None:
    """Refuse identities that would otherwise need compatibility guesses."""
    source = product.get("source")
    if source not in PRODUCT_SOURCES:
        raise ProductError(f"product has unsupported source: {source}")

    # Numeric ids are refused rather than coerced: accepting one would let a
    # barcode lose its leading zeros somewhere upstream and go unnoticed.
    if not isinstance(product.get("id"), str):
        raise ProductError("product id must be a string")
    if not product["id"]:
        raise ProductError("product id must not be empty")

    for key in ("name", "brand"):
        if not isinstance(product.get(key), str):
            raise ProductError(f"product needs a {key}")


def _check_number(
    values: dict[str, Any],
    label: str,
    key: str,
    optional: bool,
    maximum: float | None = None,
) -> None:
    """Reject a figure that is absent, not a number, negative, or too big."""
    value = values.get(key)
    if value is None:
        if optional:
            return
        raise ProductError(f"{label} has invalid {key}: None")

    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not numeric or not math.isfinite(value) or value < 0:
        raise ProductError(f"{label} has invalid {key}: {value}")
    if maximum is not None and value > maximum:
        raise ProductError(f"{label} has implausible {key}: {value}")


def _check_basis(product: Product) -> None:
    """Refuse a basis this format does not define.

    Coerced or ignored, an unknown value reads as "no caveat" — which is
    exactly the silent scaling error the key exists to make visible. The one
    rule strict enough to run when a record is merely read, and the only thing
    checked about the pair: `basis_note` is free text, and a note a reader can
    see is not worth failing the shard it sits in.
    """
    basis = product.get("basis")
    if basis is not None and basis not in PRODUCT_BASES:
        raise ProductError(
            f"{_label(product)} has unsupported basis: {basis!r}"
        )


def _label(product: Product) -> str:
    return f"{product.get('source')}:{product.get('id')}"


def _check_keys(product: Product) -> None:
    """Refuse a key this format does not define, rather than storing it."""
    unknown = sorted(set(product) - _ALLOWED_KEYS)
    if unknown:
        raise ProductError(
            f"{_label(product)} has unrecognised keys: {', '.join(unknown)}"
        )


def record_keys(product: Product) -> tuple[str, ...]:
    """The order this record's keys are written in."""
    return (*PRODUCT_KEYS, *NUTRIENT_KEYS, *BASIS_KEYS)


def assert_product_record(product: Product) -> None:
    """What a record must satisfy to be written.

    The read path is looser: 141 rows of the historical Coles scrape fail
    today's nutrition rules and none of them can be re-scraped, but nothing
    writes those rows, so nothing has to accept them here.
    """
    assert_identity(product)
    _check_keys(product)

    # Unconditional: every record is per 100 g, so every ceiling applies.
    for key in NUTRIENT_KEYS:
        maximum = None if key in ("kcal", "kj") else _MAX_PER_100G
        _check_number(
            product, _label(product), key, optional=True, maximum=maximum
        )

    _check_grams(product)
    _check_basis(product)


def _check_grams(product: Product) -> None:
    """Refuse a basis nothing can be divided by. Optional: absent means 100."""
    _check_number(product, _label(product), "grams", optional=True)
    if product.get("grams") is not None and product["grams"] <= 0:
        raise ProductError(
            f"{_label(product)} has implausible grams: {product['grams']}"
        )


def assert_exportable_product(product: Product) -> None:
    """Validate a mutable record without filling missing nutrition."""
    assert_product_record(product)


def canonicalize(product: Product, source: str | None = None) -> Product:
    """Rebuild a record in the fixed key order, dropping absent keys."""
    assert_identity(product)
    if source and product["source"] != source:
        raise ProductError(
            f"{_label(product)} cannot be written to the {source} shard"
        )

    _check_keys(product)

    # A shard's filename supplies its source, so its rows need not repeat it.
    skip = {"source"} if source else set()
    canonical = {}
    for key in record_keys(product):
        if key in skip or product.get(key) is None:
            continue
        canonical[key] = product[key]
    return canonical


def _sort_key(product: Product) -> tuple[int, tuple[int, int, str]]:
    order = PRODUCT_SOURCES.index(product["source"])
    return (order, id_sort_key(product["id"]))


def format_jsonl(products: list[Product], source: str | None = None) -> str:
    """Serialize as JSONL: one record per line, sorted, fixed key order."""
    if not products:
        return ""

    rows = sorted(products, key=_sort_key)
    return "".join(f"{dumps(canonicalize(p, source))}\n" for p in rows)


def parse_jsonl(
    text: str, source: str | None = None, label: str = "products.jsonl"
) -> list[Product]:
    """Parse a JSONL product database, ignoring blank lines.

    Line numbers are 1-based and reported on failure: a 10k-line file is not
    something anyone wants to bisect by hand.
    """
    products: list[Product] = []

    for number, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
            if source is not None:
                held = parsed.get("source")
                if held is not None and held != source:
                    raise ProductError(
                        f"record source {held} does not match {source} shard"
                    )
                # Placed first so a parsed row already reads in canonical key
                # order, which is what the shard on disk is written in.
                parsed = {"source": source, **parsed}
            assert_identity(parsed)
            _check_keys(parsed)
            # The one key checked on the way in: an unrecognised basis reads
            # as "absent", and absent means as-sold, so the record would
            # silently lose the warning it was written to carry. Nothing else
            # is, because a whole shard failing over one row would take every
            # other record down with it.
            _check_basis(parsed)
        except (ValueError, AttributeError) as cause:
            raise ProductError(
                f"{label}: line {number} is invalid: {cause}"
            ) from cause
        products.append(parsed)

    return products
