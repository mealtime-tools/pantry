"""Reading what Umall sells, and pricing it by the unit.

Umall publishes no nutrition at all: a search row carries a name, a price and,
where the title states one, a pack weight. The panel, if it is ever wanted, is
a separate concern. That split is the point — a price decays within a week and
a nutrition record does not, so the two never share a record.

Nothing here performs I/O: the parsing and pricing helpers take values and
return values, so every test runs offline.
"""

import re
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


# Umall is a general store: a quarter of what it lists is nappies, face cream,
# kitchenware and cleaning products. None of it will ever have a nutrition
# panel, so a search for food is better off never showing it.
#
# Listed by exact name rather than by keyword, because "Health & Pharmacy"
# contains supplements and "Dried Groceries" contains food: a substring rule
# over this taxonomy drops the wrong things. Anything not named here counts as
# food, so a category the store adds later is kept rather than silently lost.
NON_FOOD_TYPES = frozenset(
    name.lower()
    for name in (
        "Baby Care",
        "Bathroom & Accessories",
        "Bedding & Accessories",
        "bedside table",
        "Body Care",
        "Camping & Outdoor Accessories",
        "Cleaning Goods",
        "Cleaning Product",
        "Clothing & Accessories",
        "Computer Desk",
        "Cosmetics",
        "Cosmetics & Tools",
        "Dental Care",
        "Electrical Accessories",
        "End Table",
        "Eye & Lip Care",
        "Face Care",
        "Feminine Care",
        "Foot & Hand Care",
        "Fragrance & Air Freshener",
        "Furniture & Accessories",
        "Gardening & Accessories",
        "Hair Care",
        "Hair Dye & Styling",
        "Health & Personal Care",
        "Home & Accessories",
        "Home Decor & Living",
        "Kitchenware & Accessories",
        "Laundry",
        "Makeup Remover",
        "Mobile & Tech Accessories",
        "Outdoor",
        "Personal Care & Accessories",
        "Pets",
        "Sexual Health",
        "Skincare Sets",
        "Stationery & Entertainment",
        "Storage & Organization",
        "Sunscreen",
        "Tableware",
        "Tableware & Accessories",
        "Toilet Paper, Tissues & Paper Towels",
    )
)


def is_food(product_type: str | None) -> bool:
    """Whether a category is one a nutrition panel could ever describe.

    Alcohol, supplements and gift hampers all count: they have calories, or
    may contain something that does. Only what is unambiguously not eaten is
    excluded.
    """
    return (product_type or "").strip().lower() not in NON_FOOD_TYPES


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


# What a title says the pack holds: a size, optionally times a count. The
# count is written three ways — "3 x 200ml", "122g x 4", and in words as
# "500ml - 24 Bottles/Case" — and all three appear in the catalogue.
_PACKS = r"bottles?|packs?|pieces?|pcs?|bags?|cans?|tins?|boxes|sachets?"
_SIZE = re.compile(
    r"(?:(?P<before>\d+)\s*[x×]\s*)?"
    r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>kg|g|ml|l)\b"
    r"(?:\s*[x×]\s*(?P<after>\d+)"
    rf"|\s*[-,/]?\s*(?P<named>\d+)\s*(?:{_PACKS})\b)?",
    re.IGNORECASE,
)

# Millilitres are read as grams, exactly as a per-100 mL panel is. Both are
# exact for water and close enough for the sauces this mostly concerns.
_UNIT_GRAMS = {
    "g": Decimal(1),
    "kg": Decimal(1000),
    "ml": Decimal(1),
    "l": Decimal(1000),
}


def net_grams(title: str) -> Decimal | None:
    """What the title says is in the pack, in grams.

    Preferred over the storefront's own weight, which is what the pack weighs
    in a courier's hands. For a cup noodle those differ by the cup: 78 g of
    food in a 226 g parcel, and pricing the parcel makes packaging look like
    food. The title is the only place the net content is stated.

    The last size in the title wins, because a name that mentions two states
    the pack size second: "Mini Bowl 41g, 12 Pack, 492g".
    """
    matches = list(_SIZE.finditer(title))
    if not matches:
        return None

    found = matches[-1]
    amount = Decimal(found["amount"]) * _UNIT_GRAMS[found["unit"].lower()]
    count = found["before"] or found["after"] or found["named"]

    return (amount * int(count) if count else amount).normalize()


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
