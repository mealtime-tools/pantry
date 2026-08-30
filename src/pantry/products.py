"""The record format: what a product is, and how it is read and written.

`grams` is the weight the nutrients describe: every record is per 100 g and
states it, so storage and the wire are one shape. There is no pack or serving
size; a per-100 mL panel is stored unconverted, with a `basis_note`. Structural
fields and the cross-checked macros are enumerated because each is validated
its own way; every other nutrient is open, governed by the vocabulary.
"""

import json
import sys
from decimal import Decimal
from typing import Any

from mealtime_nutrients import NUTRIENTS, kcal_from_kj

from pantry.ids import id_sort_key
from pantry.jsonfmt import dumps

# The data owners, in the order shards are written. `localstore` is not one.
PRODUCT_SOURCES = (
    "coles",
    "woolworths",
    "afcd",
    "usda",
    "openfoodfacts",
    "manual",
)

# What the nutrients are measured against. Absent means as-sold.
PRODUCT_BASES = (
    "as_sold",
    "as_prepared",
)

# What identifies a product, in the order written. Pinning that is why JSONL.
PRODUCT_KEYS = (
    "source",
    "id",
    "name",
    "brand",
    # The GTIN the pack prints, where the source states one. Optional, and
    # never an identity: a record is keyed by source and id. It is here so a
    # retailer row can be joined to the panel another database holds for the
    # same pack, which is the only way two sources agree on one product.
    "barcode",
    "url",
    "grams",
)

# The vocabulary's own order, which already leads with the cross-checked four.
NUTRIENT_KEYS = NUTRIENTS

# Written last, so a line read by eye carries the caveat beside its figures.
# `entered` says the figures were keyed in rather than read from the source.
# Absent is the ordinary case. It exists because a record typed in under a
# retailer's id and url is otherwise indistinguishable from one the tool
# fetched, and a blocked shop is exactly when that happens.
BASIS_KEYS = ("basis", "basis_note", "entered")

# What a record says when its panel was printed per 100 mL, exact for water.
MILLILITRE_NOTE = "per 100 mL, read as 100 g"

# The same, where one column is headed for both units and so states neither.
UNSTATED_UNIT_NOTE = "per 100 g or 100 mL; the page does not say which"

Product = dict[str, Any]

# What a nutrient figure is: the decimal a label printed, or a whole number.
Figure = Decimal | int

# The basis every stored record holds, and what absence means on a frozen row.
BASIS_GRAMS = 100

# Grams per 100 g: pure salt is 38.758 g of sodium, so nothing comes near.
_MAX_PER_100G = 100

# Where a restated figure is rounded, the precision every source is read to.
_PLACES = 6

# A JSON number is read as a double, so this is the largest figure it holds.
_MAX_FIGURE = Decimal(sys.float_info.max)

# Closed, not open: `sodum` would store cleanly and hide the sodium forever.
_ALLOWED_KEYS = frozenset((*PRODUCT_KEYS, *NUTRIENT_KEYS, *BASIS_KEYS))


class ProductError(ValueError):
    """A record that would need a compatibility guess to accept."""


def is_figure(value: Any) -> bool:
    """True for a number this format holds: a whole number or a decimal."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, Decimal) and value.is_finite()


def as_decimal(value: Figure) -> Decimal:
    """One figure as a Decimal, refusing the float that has no digits.

    A float carries a binary approximation of what a label printed, so
    admitting one here is how the noise this format exists to keep out gets
    back in. Every producer states its figures as decimals instead.

    The ceiling is the other side of the same rule, and bounding both sides of
    a restatement is what keeps its arithmetic inside the decimal context.
    """
    if not is_figure(value) or abs(value) > _MAX_FIGURE:
        raise ProductError(f"{value!r} is not a figure this format holds")
    return Decimal(value)


def _restated(key: str, value: Any, to: Figure, frm: Figure) -> Any:
    """One figure against a new basis, unchanged when unknown or not moving."""
    if value is None or to == frm:
        return value

    # Multiplied before dividing: 1173 kcal over 300 g is 391, not 390.999999.
    moved = as_decimal(value) * as_decimal(to) / as_decimal(frm)
    if abs(moved) > _MAX_FIGURE:
        raise ProductError(f"{key} does not survive that weight: {moved}")

    # Division terminates in no radix, so a figure still has to stop somewhere.
    restated = round(moved, _PLACES)
    # Zero is reserved for a figure the source itself reported as zero.
    if restated == 0 and value != 0:
        raise ProductError(f"that weight rounds {key} away to zero")
    return restated


def restate(
    nutrients: dict[str, Any], frm: Figure | None, to: Figure | None = None
) -> dict[str, Any]:
    """Every nutrient moved from one weight to another, energy included."""
    # Zero or absent reads as 100 rather than being divided by.
    source = frm or BASIS_GRAMS
    target = to or BASIS_GRAMS
    return {
        key: (
            _restated(key, value, target, source)
            if key in NUTRIENT_KEYS
            else value
        )
        for key, value in nutrients.items()
    }


def rescale(product: Product, grams: Figure | None = None) -> Product:
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

    # Refused, not coerced: a coerced barcode has already lost its zeros.
    if not isinstance(product.get("id"), str):
        raise ProductError("product id must be a string")
    if not product["id"]:
        raise ProductError("product id must not be empty")

    for key in ("name", "brand"):
        if not isinstance(product.get(key), str):
            raise ProductError(f"product needs a {key}")

    # Same reason as the id: a barcode read as a number has already lost its
    # leading zeros, and a GTIN that lost one names a different product.
    barcode = product.get("barcode")
    if barcode is not None and not isinstance(barcode, str):
        raise ProductError("product barcode must be a string")

    # Only ever true. A stored `false` would read as a claim that the figures
    # were fetched, which is not something this flag is in a position to say.
    if product.get("entered", True) is not True:
        raise ProductError("product entered must be true when present")


def _check_number(
    values: dict[str, Any],
    label: str,
    key: str,
    optional: bool,
    maximum: Figure | None = None,
) -> None:
    """Reject a figure that is absent, not a number, negative, or too big."""
    value = values.get(key)
    if value is None:
        if optional:
            return
        raise ProductError(f"{label} has invalid {key}: None")

    if not is_figure(value) or value < 0:
        raise ProductError(f"{label} has invalid {key}: {value}")
    if value > (_MAX_FIGURE if maximum is None else maximum):
        raise ProductError(f"{label} has implausible {key}: {value}")


def _check_basis(product: Product) -> None:
    """Refuse a basis this format does not define.

    Coerced or ignored, an unknown value reads as "no caveat" — the silent
    scaling error the key exists to make visible. The one rule strict enough
    to run when a record is merely read, and the only thing checked about the
    pair: `basis_note` is free text.
    """
    basis = product.get("basis")
    if basis is not None and basis not in PRODUCT_BASES:
        raise ProductError(
            f"{_label(product)} has unsupported basis: {basis!r}"
        )


def _label(product: Product) -> str:
    return f"{product.get('source')}:{product.get('id')}"


def without_kilojoules(product: Product) -> Product:
    """A record stored before energy was kcal alone, read as kcal alone.

    Records written by an earlier version hold `kj`, which is no longer a key
    this format defines. Converting on the way in rather than refusing keeps
    a localstore readable, and the label's own kcal wins where it stated one.
    """
    if "kj" not in product:
        return product

    converted = dict(product)
    kilojoules = converted.pop("kj")
    if converted.get("kcal") is None and kilojoules is not None:
        converted["kcal"] = round(kcal_from_kj(kilojoules), 1)
    return converted


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
        maximum = None if key == "kcal" else _MAX_PER_100G
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
            # Decimal, so a figure reads back as the digits the line states.
            parsed = json.loads(line, parse_float=Decimal)
            if source is not None:
                held = parsed.get("source")
                if held is not None and held != source:
                    raise ProductError(
                        f"record source {held} does not match {source} shard"
                    )
                # First, so a parsed row reads in the shard's own key order.
                parsed = {"source": source, **parsed}
            parsed = without_kilojoules(parsed)
            assert_identity(parsed)
            _check_keys(parsed)
            # Checked on read: an unrecognised basis silently becomes as-sold.
            _check_basis(parsed)
        except (ValueError, AttributeError) as cause:
            raise ProductError(
                f"{label}: line {number} is invalid: {cause}"
            ) from cause
        products.append(parsed)

    return products
