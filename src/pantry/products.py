"""The record format: what a product is, and how it is read and written.

Every nutrient is grams per 100 g. One rule, no exceptions: a consumer scales
by `grams / 100` at the point of display, and storing a pre-scaled value or a
second unit would make editing an amount wrong in a way no test would catch.

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
from pantry.nutrition import (
    CALORIE_FREE,
    NUTRIENTS,
    assert_usable_nutrients,
)

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
    "serving_size",
    "serving_unit",
    "total_size",
    "total_unit",
)

# Energy and the four macros, written next. Enumerated where the vocabulary
# nutrients are not, because these are the figures cross-checked against each
# other and against the 100 g the panel describes.
CORE_NUTRIENTS = ("kcal", "kj", "protein", "fat", "carbs")

# Written last, after the figures they qualify, so a line read by eye carries
# the caveat beside the numbers it applies to.
BASIS_KEYS = ("basis", "basis_note")

Product = dict[str, Any]

_REQUIRED_NUMBERS = ("kcal", "protein", "fat", "carbs")

# Figures that may be absent and are not nutrients, so the vocabulary rules do
# not apply: `kj` is stored only when a label printed it, and a pack size is a
# mass rather than a share of one.
_OPTIONAL_SIZES = ("kj", "serving_size", "total_size")

# Grams per 100 g, so 100 is the ceiling for every nutrient alike. Pure table
# salt is only 38.758 g of sodium, so nothing edible comes near it.
_MAX_PER_100G = 100

# Every key a record may hold. Closed rather than open: an unrecognised key is
# a misspelling far more often than it is a new field, and `sodum` would store
# cleanly and then no consumer would ever find the sodium again.
_ALLOWED_KEYS = frozenset(
    (*PRODUCT_KEYS, *CORE_NUTRIENTS, *NUTRIENTS, *BASIS_KEYS)
)


class ProductError(ValueError):
    """A record that would need a compatibility guess to accept."""


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
    product: Product, key: str, optional: bool, maximum: float | None = None
) -> None:
    """Reject a figure that is absent, not a number, negative, or too big."""
    value = product.get(key)
    if value is None:
        if optional:
            return
        raise ProductError(f"{_label(product)} has invalid {key}: None")

    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not numeric or not math.isfinite(value) or value < 0:
        raise ProductError(f"{_label(product)} has invalid {key}: {value}")
    if maximum is not None and value > maximum:
        raise ProductError(f"{_label(product)} has implausible {key}: {value}")


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
    """The order this record's keys are written in.

    Vocabulary nutrients sort alphabetically, which is what removes the need to
    enumerate them: adding one changes no order and diffs no other line.
    """
    held = sorted(key for key in product if key in NUTRIENTS)
    return (*PRODUCT_KEYS, *CORE_NUTRIENTS, *held, *BASIS_KEYS)


def assert_product_record(product: Product) -> None:
    """Structural checks only, safe for the frozen historical Coles rows.

    141 of those rows fail today's stricter nutrition rules and none of them
    can be re-scraped, so the shard is validated for shape and not for
    plausibility.
    """
    assert_identity(product)
    _check_keys(product)

    for key in _REQUIRED_NUMBERS:
        _check_number(product, key, optional=False)
    for key in _OPTIONAL_SIZES:
        _check_number(product, key, optional=True)

    # One rule for the whole vocabulary. Capped here rather than with the panel
    # rules because both zero-energy paths return before those run, and every
    # path that authors a record reaches this function.
    for key in NUTRIENTS:
        _check_number(product, key, optional=True, maximum=_MAX_PER_100G)

    _check_basis(product)


def assert_exportable_product(product: Product) -> None:
    """Strict validation for mutable and newly imported records."""
    assert_product_record(product)

    # A confirmed zero-calorie record is the one shape the nutrition rules
    # cannot express, so it is checked for internal consistency instead. A
    # calorie-free nutrient is exempt: table salt is a genuine 0 kcal record
    # with 38.758 g of sodium in it.
    if product.get("kcal") == 0:
        claimed = (*CORE_NUTRIENTS, *NUTRIENTS)
        for key in (k for k in claimed if k not in CALORIE_FREE):
            value = product.get(key)
            if value is not None and value != 0:
                raise ProductError(
                    f"{_label(product)} has zero energy but "
                    f"non-zero {key}: {value}"
                )
        return

    assert_usable_nutrients(product)


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
    return {
        key: product[key]
        for key in record_keys(product)
        if key not in skip and product.get(key) is not None
    }


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
