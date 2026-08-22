"""The record format: what a product is, and how it is read and written.

Nutrients are per 100 g, everywhere, always. A consumer scales by
`grams / 100` at the point of display; storing a pre-scaled value would make
editing an amount wrong in a way no test would catch.

Every nutrient is grams except `sodium`, which is milligrams: it is the unit
every nutrition panel prints that row in, so the common case needs no
conversion at all.
"""

import json
import math
from typing import Any

from pantry.ids import id_sort_key
from pantry.jsonfmt import dumps
from pantry.nutrition import MG_PER_G, assert_usable_nutrients

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

# The order keys are written in. The scrape emitted several key orders and no
# particular record order, which turned an edit to one product into a diff
# across the whole file. Pinning both is the entire point of storing JSONL.
PRODUCT_KEYS = (
    "source",
    "id",
    "name",
    "brand",
    "kj",
    "fat",
    "carbs",
    "protein",
    "fiber",
    "sugar",
    # Milligrams, not grams. The only key whose unit differs from its
    # neighbours, because the label it is read off is written that way.
    "sodium",
    "kcal",
    # The basis sits with the figures it qualifies rather than with the
    # packaging fields, so a line read by eye carries the caveat beside the
    # numbers it applies to.
    "basis",
    "basis_note",
    "url",
    "serving_size",
    "serving_unit",
    "total_size",
    "total_unit",
)

Product = dict[str, Any]

_REQUIRED_NUMBERS = ("kcal", "protein", "fat", "carbs")
_OPTIONAL_NUMBERS = ("kj", "fiber", "sugar", "serving_size", "total_size")

# 100 g of sodium per 100 g, in the milligrams sodium is stored in. The
# nutrition rules cap every other figure at 100 g, and pure table salt is only
# 38,758 mg, so nothing edible comes near this.
_MAX_SODIUM_MG = 100 * MG_PER_G


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


def assert_product_record(product: Product) -> None:
    """Structural checks only, safe for the frozen historical Coles rows.

    141 of those rows fail today's stricter nutrition rules and none of them
    can be re-scraped, so the shard is validated for shape and not for
    plausibility.
    """
    assert_identity(product)

    for key in _REQUIRED_NUMBERS:
        _check_number(product, key, optional=False)
    for key in _OPTIONAL_NUMBERS:
        _check_number(product, key, optional=True)

    # Checked here rather than with the panel rules because both zero-energy
    # paths return before those run, and sodium is the only figure they carry
    # through. Every path that authors one reaches this function.
    _check_number(product, "sodium", optional=True, maximum=_MAX_SODIUM_MG)

    _check_basis(product)


def assert_exportable_product(product: Product) -> None:
    """Strict validation for mutable and newly imported records."""
    assert_product_record(product)

    # A confirmed zero-calorie record is the one shape the nutrition rules
    # cannot express, so it is checked for internal consistency instead.
    # Sodium is absent from the list below on purpose: it carries no energy,
    # so table salt is a genuine 0 kcal record with 38,758 mg of it.
    if product.get("kcal") == 0:
        for key in ("kj", "protein", "fat", "carbs", "fiber", "sugar"):
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

    # A shard's filename supplies its source, so its rows need not repeat it.
    skip = {"source"} if source else set()
    ordered = {
        key: product[key]
        for key in PRODUCT_KEYS
        if key not in skip and product.get(key) is not None
    }

    # Anything a new import starts emitting is kept rather than dropped.
    for key, value in product.items():
        if key not in ordered and key not in skip:
            ordered[key] = value

    return ordered


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
