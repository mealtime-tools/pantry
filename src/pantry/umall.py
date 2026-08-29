"""Reading Umall's catalogue, and pricing what it sells by the unit.

Umall is a Shopify storefront, so its whole catalogue is one cursor-paged
query and no page has to be scraped. It publishes no nutrition at all: a row
here carries identity, weight and price, and the panel is whatever
`off:<barcode>` already holds. That split is the point — a price decays within
a week and a nutrition record does not, so the two never share a record.

Nothing here performs I/O: a payload arrives as parsed JSON and leaves as a
row, so every test runs offline.
"""

from decimal import Decimal, InvalidOperation
from typing import Any

STORE_URL = "https://www.umall.com.au"

# Money and unit prices, to the fraction of a cent a division can produce.
_MONEY_PLACES = Decimal("0.0001")

# GS1 prefixes reserved for codes a shop issues to itself. They pass a check
# digit and mean nothing outside the store that printed them, so a lookup
# against them would join on a coincidence.
_IN_STORE_PREFIXES = frozenset(
    ("02", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29")
)

# A GTIN is one of four lengths; anything else is an internal part number.
_GTIN_LENGTHS = frozenset((8, 12, 13, 14))

# Shopify states weight in one of four units. Only two convert exactly, and a
# guessed pound is a wrong unit price rather than a missing one.
_TO_GRAMS = {"GRAMS": Decimal(1), "KILOGRAMS": Decimal(1000)}


def _check_digit_holds(barcode: str) -> bool:
    """Whether the last digit is the one the other digits imply."""
    digits = [int(char) for char in barcode][::-1]
    weighted = sum(
        digit * (3 if index % 2 else 1)
        for index, digit in enumerate(digits[1:], 1)
    )
    return (10 - weighted % 10) % 10 == digits[0]


def is_external_gtin(barcode: str | None) -> bool:
    """Whether this code identifies the product outside Umall.

    Only these can be joined to another database. An in-store code is still
    the row's identity, because it is what Umall calls the product; it just
    cannot be looked up anywhere else.
    """
    if not barcode or not barcode.isdigit():
        return False
    if len(barcode) not in _GTIN_LENGTHS:
        return False
    if barcode[:2] in _IN_STORE_PREFIXES:
        return False

    return _check_digit_holds(barcode)


def _decimal(value: Any) -> Decimal | None:
    """A finite, non-negative number, or nothing.

    Weights arrive as JSON numbers and prices as strings, so both are read
    through their text: a float has no decimal digits of its own to keep.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    if not parsed.is_finite() or parsed < 0:
        return None

    return parsed


def _grams(variant: dict[str, Any]) -> Decimal | None:
    """The pack weight in grams, where the store stated one it can state.

    Zero is not a weight: produce sold by the piece reports it, and treating
    it as one would divide by zero. Absent means the pack cannot be priced by
    weight, which is a different answer from free.
    """
    factor = _TO_GRAMS.get(str(variant.get("weightUnit") or ""))
    weight = _decimal(variant.get("weight"))
    if factor is None or weight is None or weight == 0:
        return None

    return (weight * factor).normalize()


def catalog_entry(node: dict[str, Any]) -> dict[str, Any] | None:
    """One Storefront product node as a catalogue row, or nothing.

    Refused rather than repaired: a row with no barcode has no identity, and
    one with no price is not an offer. Both happen, and both are rows this
    catalogue is better off not holding than holding a guess about.
    """
    variants = (node.get("variants") or {}).get("nodes") or []
    if not variants:
        return None

    variant = variants[0]
    barcode = variant.get("barcode")
    name = str(node.get("title") or "")
    price = _decimal((variant.get("price") or {}).get("amount"))
    if not barcode or not name or price is None:
        return None

    entry: dict[str, Any] = {
        "id": str(barcode),
        "name": name,
        "brand": str(node.get("vendor") or ""),
        "type": str(node.get("productType") or ""),
        "tags": [str(tag) for tag in node.get("tags") or []],
        "price": price,
        "currency": str(
            (variant.get("price") or {}).get("currencyCode") or ""
        ),
    }

    grams = _grams(variant)
    if grams is not None:
        # Not `grams`: that key names the weight a panel describes, and
        # `rescale` overwrites it. A pack weight under it would be relabelled
        # by `--grams` rather than left alone.
        entry["pack_grams"] = grams

    entry["available"] = bool(variant.get("availableForSale"))
    entry["url"] = f"{STORE_URL}/products/{node.get('handle') or ''}"

    # Only where another database could hold the panel this row lacks.
    if is_external_gtin(str(barcode)):
        entry["ref"] = f"off:{barcode}"

    return entry


def _rate(price: Decimal | None, quantity: Decimal | None) -> Decimal | None:
    """What one unit of `quantity` costs, where both are known and real."""
    if price is None or quantity is None or quantity <= 0:
        return None

    return (price / quantity).quantize(_MONEY_PLACES).normalize()


def price_per_100_grams(
    price: Decimal | None, grams: Decimal | None
) -> Decimal | None:
    """What 100 g of this product costs."""
    if grams is None or grams <= 0:
        return None

    return _rate(price, grams / 100)


def _pack_total(
    grams: Decimal | None, per_100_grams: Decimal | None
) -> Decimal | None:
    """How much of a nutrient the whole pack holds."""
    if grams is None or per_100_grams is None:
        return None

    return per_100_grams * grams / 100


def price_per_100_kcal(
    price: Decimal | None,
    grams: Decimal | None,
    kcal_per_100_grams: Decimal | None,
) -> Decimal | None:
    """What 100 kcal of this product costs.

    A product with no energy in it has no price per calorie, which is not the
    same as a cheap one: the answer is unknown, so it is absent.
    """
    total = _pack_total(grams, kcal_per_100_grams)
    if total is None or total <= 0:
        return None

    return _rate(price, total / 100)


def price_per_gram(
    price: Decimal | None,
    grams: Decimal | None,
    per_100_grams: Decimal | None,
) -> Decimal | None:
    """What one gram of a nutrient costs, at this pack's price."""
    total = _pack_total(grams, per_100_grams)
    if total is None or total <= 0:
        return None

    return _rate(price, total)
