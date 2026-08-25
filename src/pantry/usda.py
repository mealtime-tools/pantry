"""Reading one food out of FoodData Central.

A documented API with a key and a rate limit, so none of the fetcher's block
rules or page budget apply. `foodNutrients[].amount` is per 100 g for every
data type, which is already Pantry's basis, so only the unit is converted on
the way in; `labelNutrients` is per serving and deliberately ignored, since
reading it would make every recipe wrong by serving size over 100 g.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any

from agentcli import RemoteError
from mealtime_nutrients import kcal_from_kj

from pantry.products import BASIS_GRAMS, Figure, Product, as_decimal

BASE_URL = "https://api.nal.usda.gov/fdc/v1"

TIMEOUT_S = 30

# FoodData Central nutrient ids; kJ is the fallback for SI-only records.
KCAL_ID = 1008
KJ_ID = 1062
NUTRIENT_IDS = {
    1003: "protein",
    1004: "fat",
    1005: "carbs",
    1079: "fiber",
    2000: "sugar",
    1093: "sodium",
}

# The ids published in milligrams, stated because `unitName` may be absent.
MILLIGRAM_IDS = frozenset({1093})

# Milligrams to grams is three decimal places, and moving them loses nothing.
MG_SHIFT = 3


def _grams(nutrient_id: int, amount: Decimal) -> Decimal:
    """One figure in the unit a record holds, whatever the API published."""
    if nutrient_id not in MILLIGRAM_IDS:
        return amount
    return amount.scaleb(-MG_SHIFT)


def _amounts(food: dict[str, Any]) -> dict[int, Decimal]:
    """Nutrient id to per-100 g amount, keeping only usable figures."""
    found: dict[int, Decimal] = {}
    for entry in food.get("foodNutrients") or []:
        nutrient = entry.get("nutrient") or {}
        amount = entry.get("amount")

        # A missing or non-numeric amount is absent, never zero.
        if not isinstance(nutrient.get("id"), int):
            continue
        try:
            found[nutrient["id"]] = as_decimal(amount)
        except ValueError:
            continue

    return found


def _energy_kcal(amounts: dict[int, Decimal]) -> Figure:
    """Energy in kcal, converted from kJ only when kcal is absent."""
    if KCAL_ID in amounts:
        return amounts[KCAL_ID]
    if KJ_ID in amounts:
        return round(kcal_from_kj(amounts[KJ_ID]), 1)

    raise RemoteError("the USDA record carries no energy figure")


def _brand(food: dict[str, Any]) -> str:
    """The most specific brand the record offers, or nothing at all.

    `brandName` is the label a person would recognise; `brandOwner` is the
    company behind it. Neither is invented when both are absent.
    """
    for key in ("brandName", "brandOwner"):
        value = food.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def to_product(food: dict[str, Any]) -> Product:
    """Turn one FoodData Central food into a Pantry record.

    Every nutrient the record publishes is carried; every one it omits stays
    omitted.
    """
    identifier = food.get("fdcId")
    if not isinstance(identifier, int):
        raise RemoteError("the USDA response carries no fdcId")

    description = food.get("description")
    if not isinstance(description, str) or not description.strip():
        raise RemoteError(f"USDA food {identifier} has no description")

    amounts = _amounts(food)
    product: Product = {
        "source": "usda",
        "id": str(identifier),
        "name": description.strip(),
        "brand": _brand(food),
        # Stated rather than left out, though this API publishes only 100 g.
        "grams": BASIS_GRAMS,
        "kcal": _energy_kcal(amounts),
        "url": (
            "https://fdc.nal.usda.gov/fdc-app.html"
            f"#/food-details/{identifier}/nutrients"
        ),
    }
    for nutrient_id, field in NUTRIENT_IDS.items():
        if nutrient_id in amounts:
            product[field] = _grams(nutrient_id, amounts[nutrient_id])

    return product


def fetch_food(
    fdc_id: str,
    key: str,
    *,
    opener: Any = None,
) -> dict[str, Any]:
    """Read one food by its FoodData Central id.

    The opener is injectable so the tests never reach the network. The key
    travels in the query string because that is the only form this API accepts;
    it is never written to output.
    """
    query = urllib.parse.urlencode({"api_key": key})
    url = f"{BASE_URL}/food/{urllib.parse.quote(fdc_id)}?{query}"
    request = urllib.request.Request(
        url, headers={"Accept": "application/json"}
    )
    open_url = opener or urllib.request.urlopen

    try:
        with open_url(request, timeout=TIMEOUT_S) as response:
            # Decimal, so an amount arrives as the digits the API published.
            payload = json.loads(
                response.read().decode("utf-8"), parse_float=Decimal
            )
    except urllib.error.HTTPError as exc:
        # The key is in the url, so the url never reaches the message.
        raise RemoteError(
            f"FoodData Central refused food {fdc_id} with HTTP {exc.code}"
        ) from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RemoteError(f"could not reach FoodData Central: {exc}") from None
    except json.JSONDecodeError:
        raise RemoteError(
            "FoodData Central returned a malformed body"
        ) from None

    if not isinstance(payload, dict):
        raise RemoteError("FoodData Central returned an unexpected body")

    return payload
