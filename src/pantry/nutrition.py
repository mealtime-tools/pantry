"""Reading a nutrition panel, from a site's data or from text a user pasted.

Everything downstream of this file is grams per 100 g, and everything upstream
of it is a label written for humans: two columns, trace amounts written as a
bound, energy in kilojoules, milligrams for the minerals, sub-rows indented
under their parent. This is where that becomes numbers, and where a panel that
did not parse is refused.

What a nutrient is called, what unit it is written in and how much energy it
carries all live in `nutrition`, the domain the mealtime tools share. What is
left here is the part that is about a per-100 g product record: the two
ceilings, the zero-calorie declaration, and the column and layout heuristics a
pasted label needs and a structured row does not.
"""

import math
import re
from typing import Any

from nutrition import energy, figures, vocabulary

# Every nutrient a record may carry beyond energy and the three macros, taken
# from the shared vocabulary rather than listed again. The macros are excluded
# because they are enumerated in `products` and cross-checked against each
# other; everything else is governed by one rule and sorts alphabetically, so
# the vocabulary growing changes nothing here.
NUTRIENTS = tuple(
    key for key in vocabulary.NUTRIENTS if key not in energy.KCAL_PER_GRAM
)

# The nutrients a confirmed zero-energy record may still hold. A mineral has no
# calories, so table salt is a genuine 0 kcal record with 38.758 g of sodium;
# a sugar figure beside a zero energy is a half-parsed panel.
CALORIE_FREE = tuple(
    key for key in NUTRIENTS if not vocabulary.carries_energy(key)
)

# No food exceeds pure fat, which is 900 kcal per 100 g.
_MAX_KCAL_PER_100G = 900

# Rounding on a label lets the three macros total slightly over 100 g.
_MASS_TOLERANCE = 105

# The three figures the mass ceiling is measured over, and the three the
# Atwater sum is made of: the same three, read off the shared vocabulary.
_MACROS = tuple(energy.KCAL_PER_GRAM)

# The sodium row, and only the sodium row: the word opens the line and its
# figure follows immediately, with nothing between but the "less than" a trace
# amount is printed as. Anchored and adjacent so that an ingredient list
# naming sodium -- "Sodium Bicarbonate (500)" -- falls through to the skip rule
# instead. A row this does not recognize reads as absent, which is the safe
# answer: a missing sodium is unknown by contract, a wrong one is not.
_SODIUM_ROW = re.compile(
    r"^\s*sodium\b:?\s*(?:less\s+than\s+)?[<\d]", re.IGNORECASE
)

# The rows this parser recognizes, in the order it tries them. First match
# wins, so sodium leads: any other line naming it is skipped on the next rule,
# which is what keeps "Sodium Bicarbonate (500)" out of the *carbohydrates* row
# it would otherwise match on "bicarbonate". Skipped rows come next: "-
# Saturated" would otherwise match the fat row, and "Sugars" and "Dietary
# Fibre" both sit under carbohydrate on a label.
#
# Only a pasted label needs this. A structured source states its own row names
# and `figures.read_rows` resolves them whole, which is why the two paths do
# not share a pattern: hunting a name out of a line is the ambiguity, not the
# vocabulary.
_ROWS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Read, unlike the salt row below it: salt is 2.5 times its sodium, so
    # taking one for the other would overstate the figure by 150 percent.
    ("sodium", _SODIUM_ROW),
    (
        "skip",
        re.compile(
            r"saturat|trans|monounsat|polyunsat|sodium|salt"
            r"|cholesterol|potassium",
            re.IGNORECASE,
        ),
    ),
    ("sugar", re.compile(r"sugar", re.IGNORECASE)),
    ("dietary_fiber", re.compile(r"fib(?:re|er)", re.IGNORECASE)),
    ("protein", re.compile(r"protein", re.IGNORECASE)),
    ("carbohydrates", re.compile(r"carb", re.IGNORECASE)),
    ("fat", re.compile(r"fat", re.IGNORECASE)),
    ("kcal", re.compile(r"energy|kilojoule|calorie", re.IGNORECASE)),
)

# The units a pack or serving size is written in, at the end of the figure.
# Not a nutrient unit: a pack is millilitres as often as grams, and neither is
# a share of the 100 g a panel describes.
_UNIT = re.compile(r"(kg|ml|l|g)\s*$", re.IGNORECASE)

_PER_HUNDRED = re.compile(r"per\s*100\s*(?:g|ml)", re.IGNORECASE)
_PER_SERVING = re.compile(r"per\s*serv", re.IGNORECASE)


class NutritionError(ValueError):
    """A panel that is not worth storing, or a declaration that conflicts."""


def parse_amount(text: str | None) -> tuple[float | None, str | None]:
    """Split "450g" or "650 ml" into the number and unit a record stores.

    Both halves or neither. A community quantity such as "4 * 125 g (500 g)"
    reads as the number 4, and storing that without a unit would claim a
    450 g loaf and a 4-pack are the same size — a wrong value, not a missing
    one.
    """
    match = _UNIT.search(text) if text else None
    if match is None:
        return (None, None)

    found = figures.figures(text)
    return (found[0][0] if found else None, match.group(1).lower())


def _row_key(label: str) -> str | None:
    for key, pattern in _ROWS:
        if pattern.search(label):
            return key
    return None


def _per_hundred_first(text: str) -> bool:
    """Whether the per-100 g figures are the first column, not the last.

    The Australian standard puts "per serving" first and "per 100 g" second,
    so the last number on a row is the right one by default. A label that
    reverses them says so in its header, the only place the two are named.
    """
    hundred = _PER_HUNDRED.search(text)
    serving = _PER_SERVING.search(text)
    if not hundred or not serving:
        return False
    return hundred.start() < serving.start()


def _column(found: list[tuple[float, str]], first: bool):
    """The figure belonging to the per-100 g column of one row."""
    if not found:
        return None
    return found[0] if first else found[-1]


def parse_panel(text: str) -> dict[str, float]:
    """Read a nutrition panel out of pasted text.

    Rows it does not recognize are ignored and rows that are absent stay
    absent; `nutrients_for_storage` decides whether what came out is enough.
    """
    first = _per_hundred_first(text)
    panel: dict[str, float] = {}

    for line in text.split("\n"):
        key = _row_key(line)
        if key is None or key == "skip":
            continue

        found = figures.figures(line)
        if not found:
            continue

        if key == "kcal":
            _read_energy(panel, found, first)
            continue

        chosen = _column(found, first)
        if not chosen:
            continue

        panel[key] = figures.grams(key, chosen[0], chosen[1])

    return panel


def _read_energy(
    panel: dict[str, float], found: list[tuple[float, str]], first: bool
) -> None:
    """Energy is the one row that can carry two units in a single column.

    A label writing "1000kJ (239Cal)" already did the arithmetic, and its own
    calorie figure beats converting the kilojoules ourselves. Both forms are
    kept when kilojoules were printed: kcal because everything downstream
    reads it, kj because deriving it back would invent a figure nobody wrote.
    """
    calories = [q for q in found if q[1] in figures.KCAL_SPELLINGS]
    chosen = _column(calories or found, first)
    if not chosen:
        return

    value, unit = chosen
    panel["kcal"] = figures.energy_kcal(value, unit)

    # Anything that is not a calorie spelling is kilojoules, a bare figure
    # included: that is what an AU panel prints when it prints one unit.
    if unit not in figures.KCAL_SPELLINGS:
        panel["kj"] = value


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


def assert_usable_nutrients(panel: dict[str, Any]) -> None:
    """Refuse a panel that is not worth storing.

    The failure this exists to prevent is a half-parsed panel becoming a
    product with inferred zero calories: nothing downstream would flag it, and
    every recipe using that ingredient would quietly under-count.
    """
    kcal = panel.get("kcal")
    if kcal is None or not math.isfinite(kcal) or kcal <= 0:
        raise NutritionError(f"nutrition panel has no usable energy: {kcal}")
    if kcal > _MAX_KCAL_PER_100G:
        raise NutritionError(
            f"nutrition panel has more energy than pure fat: {kcal} kcal"
        )

    for key in _MACROS:
        _check_mass(panel, key)

    # Absent is fine (plenty of labels omit them) but present and wrong is
    # not. One rule for the whole vocabulary: every figure is grams per 100 g,
    # so the mass check is the only check any of them needs.
    for key in NUTRIENTS:
        if panel.get(key) is not None:
            _check_mass(panel, key)

    # Catches the two mistakes a per-100 g figure cannot survive: a
    # per-serving column read by mistake, and a milligram figure landing in a
    # gram field.
    mass = sum(panel[key] for key in _MACROS)
    if mass > _MASS_TOLERANCE:
        raise NutritionError(
            f"nutrition panel holds {mass:.1f} g of macros per 100 g"
        )

    # Whether the macros can account for the energy printed beside them. The
    # mass ceiling catches a column read from the wrong place; this catches a
    # panel whose columns were read from two different places, which is the
    # same figure being plausible and wrong.
    #
    # Ingress only, and deliberately: 635 of the 11,885 frozen rows do not
    # reconcile, so `assert_product_record` never asks. Raised as the
    # library's own `EnergyError` rather than restated as a `NutritionError`,
    # because the rule and the tolerance are the library's and a second
    # message would drift from them.
    energy.assert_energy_reconciles(float(kcal), panel)


def nutrients_for_storage(
    panel: dict[str, float], zero_calorie: bool = False
) -> dict[str, float]:
    """Return a strict panel, or explicit zeros after checking the claim."""
    if not zero_calorie:
        assert_usable_nutrients(panel)
        return panel

    # A confirmation may fill an absent or all-zero panel, but never erase
    # nutrition that was actually printed. A calorie-free nutrient is exempt
    # because it is not part of the energy claim being confirmed. An impossible
    # figure is not waved through with it -- `_check_number` is what refuses
    # that, on the record every one of these panels becomes.
    for key, value in panel.items():
        if key in CALORIE_FREE:
            continue
        if value is not None and (not math.isfinite(value) or value != 0):
            raise NutritionError(
                f"--zero-calorie conflicts with nutrition panel {key}: {value}"
            )

    zeroed: dict[str, float] = {"kcal": 0}
    zeroed.update({key: 0 for key in _MACROS})
    zeroed.update(
        {k: panel[k] for k in CALORIE_FREE if panel.get(k) is not None}
    )

    return zeroed
