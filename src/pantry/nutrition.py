"""What a stored panel has to survive, per 100 g.

Reading a panel is not this module's job. A figure arrives already separated
from its name and its unit -- `nutrition.panel` does that, the same way for a
string a caller passed and for a retailer's own rows -- and what is left here
is the part that is actually pantry's: whether a per-100 g panel is worth
storing at all.

Turning a photographed label or a pasted web page into that format is the
agent's job, not this CLI's. A CLI that guesses at prose has to guess wrong
sometimes, and every wrong guess is a number somebody trusts. Everything that
used to guess -- which column was per 100 g, which line was which row, which
of two figures on a line to take -- is gone, and so is every bug it caused.
"""

import math
import re
from typing import Any

from nutrition import energy, vocabulary

# Every nutrient a record may carry beyond energy and the three macros, taken
# from the shared vocabulary rather than listed again. The three are excluded
# because they are enumerated in `products` and cross-checked against each
# other; everything else is governed by one rule and sorts alphabetically, so
# the vocabulary growing changes nothing here.
#
# `energy.REQUIRED` and not `energy.KCAL_PER_GRAM`: alcohol has an Atwater
# factor but is not one of the three a panel must state, so it belongs here,
# storable when a source publishes an ethanol figure and absent otherwise.
NUTRIENTS = tuple(
    key for key in vocabulary.NUTRIENTS if key not in energy.REQUIRED
)

# The nutrients a confirmed zero-energy record may still hold. A mineral has no
# calories, so table salt is a genuine 0 kcal record with 38.758 g of sodium;
# a sugar figure beside a zero energy is a contradiction.
CALORIE_FREE = tuple(
    key for key in NUTRIENTS if not vocabulary.carries_energy(key)
)

# No food exceeds pure fat, which is 900 kcal per 100 g.
_MAX_KCAL_PER_100G = 900

# Rounding on a label lets the three macros total slightly over 100 g.
_MASS_TOLERANCE = 105

# A pack or serving size, which is packaging rather than nutrition: "450g" is
# a size, not a panel row, and it is the one written figure left in this file.
# A pack is millilitres as often as grams, and neither is a share of the 100 g
# a panel describes.
_SIZE = re.compile(r"^\s*([\d,.]+)\s*(kg|ml|l|g)\s*$", re.IGNORECASE)


class NutritionError(ValueError):
    """A panel that is not worth storing, or a declaration that conflicts."""


def parse_amount(text: str | None) -> tuple[float | None, str | None]:
    """Split "450g" or "650 ml" into the number and unit a record stores.

    Both halves or neither, and only when the whole string is one size. A
    quantity such as "4 * 125 g (500 g)" has no single answer, so it gets
    none: storing the 4 without a unit would claim a 450 g loaf and a 4-pack
    are the same size, which is a wrong value rather than a missing one.
    """
    found = _SIZE.match(text or "")
    if found is None:
        return (None, None)

    try:
        return (float(found.group(1).replace(",", "")), found.group(2).lower())
    except ValueError:
        return (None, None)


def _check_mass(panel: dict[str, Any], key: str) -> None:
    """Refuse an amount that is absent, impossible, or over 100 g per 100 g."""
    value = panel.get(key)
    if value is None:
        raise NutritionError(f"nutrition panel has no {key}")
    if not math.isfinite(value) or value < 0:
        raise NutritionError(
            f"nutrition panel has an impossible {key}: {value}"
        )
    if value > 100:
        raise NutritionError(
            f"nutrition panel has more than 100 g of {key} per 100 g"
        )


def reconciliation_note(panel: dict[str, float]) -> str | None:
    """Why the macros cannot account for the stated energy, if they cannot.

    A warning rather than a refusal, and that split is deliberate. The check is
    shared with eatout, which refuses on it because its data is reviewed by
    hand. A scraped corpus is not: roughly a twentieth of real retailer panels
    fail for honest reasons -- fibre energy an Australian label excludes from
    carbohydrate, polyols in a sugar-free product, alcohol nobody declared.
    """
    try:
        energy.assert_energy_reconciles(panel.get("kcal") or 0.0, panel)
    except ValueError as error:
        return str(error)

    return None


def assert_usable_nutrients(panel: dict[str, Any]) -> None:
    """Refuse a panel that is not worth storing.

    The failure this exists to prevent is a partial panel becoming a product
    with inferred zero calories: nothing downstream would flag it, and every
    recipe using that ingredient would quietly under-count.
    """
    kcal = panel.get("kcal")
    if kcal is None or not math.isfinite(kcal) or kcal <= 0:
        raise NutritionError(f"nutrition panel has no usable energy: {kcal}")
    if kcal > _MAX_KCAL_PER_100G:
        raise NutritionError(
            f"nutrition panel has more energy than pure fat: {kcal} kcal"
        )

    for key in energy.REQUIRED:
        _check_mass(panel, key)

    # Absent is fine -- plenty of labels omit them -- but present and wrong is
    # not. One rule for the whole vocabulary, because every figure is grams per
    # 100 g and the mass check is the only check any of them needs.
    for key in NUTRIENTS:
        if panel.get(key) is not None:
            _check_mass(panel, key)

    # The one mistake a per-100 g figure cannot survive on its own: a
    # per-serving column stored as if it described 100 g.
    mass = sum(panel[key] for key in energy.REQUIRED)
    if mass > _MASS_TOLERANCE:
        raise NutritionError(
            f"nutrition panel holds {mass:.1f} g of macros per 100 g"
        )


def nutrients_for_storage(
    panel: dict[str, float], zero_calorie: bool = False
) -> dict[str, float]:
    """Return a strict panel, or explicit zeros after checking the claim."""
    if not zero_calorie:
        assert_usable_nutrients(panel)
        return panel

    # A confirmation may fill an absent or all-zero panel, but never erase
    # nutrition that was actually stated. A calorie-free nutrient is exempt
    # because it is not part of the energy claim being confirmed.
    for key, value in panel.items():
        if key in CALORIE_FREE:
            continue
        if value is not None and (not math.isfinite(value) or value != 0):
            raise NutritionError(
                f"--zero-calorie conflicts with nutrition panel {key}: {value}"
            )

    zeroed: dict[str, float] = {"kcal": 0.0}
    zeroed.update({key: 0.0 for key in energy.REQUIRED})
    zeroed.update(
        {k: panel[k] for k in CALORIE_FREE if panel.get(k) is not None}
    )

    return zeroed
