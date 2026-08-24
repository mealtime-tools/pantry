"""Validate structured nutrition rows from retailer and database sources.

Everything returned by this file is grams per 100 g, and everything upstream
of it is a row whose source already separated its name from its value.
"""

import math
import re

from mealtime_nutrients import (
    CORE_NUTRIENTS,
    NUTRIENTS,
    kcal_from_kj,
    row_pattern,
)

# Labels print milligrams and micrograms; a record holds grams. Only here.
_UNITS_PER_GRAM = {
    "mg": 1000,
    "mcg": 1_000_000,
    "µg": 1_000_000,
    "μg": 1_000_000,
}

# Six places would quantise 2.4 µg, or 2.4e-06 g, 17 percent low.
GRAM_PLACES = 12

# No food exceeds pure fat, which is 900 kcal per 100 g.
_MAX_KCAL_PER_100G = 900

# Rounding on a label lets the three macros total slightly over 100 g.
_MASS_TOLERANCE = 105

# Both spellings of micro, else the trailing \b makes "1.2µg" a bare 1.0.
_QUANTITY = re.compile(
    r"(-?[\d,]+(?:\.\d+)?)\s*(kcal|cal|kj|mcg|µg|μg|mg|g|ml)?\b",
    re.IGNORECASE,
)

# Anchored and adjacent, so "Sodium Bicarbonate (500)" reaches the skip rule.
_SODIUM_ROW = re.compile(
    r"^\s*sodium\b:?\s*(?:less\s+than\s+)?[<\d]", re.IGNORECASE
)

# The same row named, not hunted: a stated name needs no adjacent figure.
_SODIUM_NAME = re.compile(r"^\s*sodium\b[\s(]*(?:mg|g)?\)?\s*$", re.IGNORECASE)

# "Sodium (mg)" against a bare 400 states its unit rather than omitting it.
_NAME_UNIT = re.compile(r"\(?\b(mcg|µg|μg|mg|g)\b\)?\s*$", re.IGNORECASE)

# The rows pantry hand-writes, in the order tried: a sub-row above its total.
_HAND_WRITTEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Before the skip rule: salt is 2.5 times its sodium, not the same figure.
    ("sodium", _SODIUM_ROW),
    # "Sodium Bicarbonate (500)" would otherwise reach carbs on "bicarbonate".
    ("skip", re.compile(r"sodium|salt", re.IGNORECASE)),
    # Longest first: "polyunsaturated" nests "unsaturated" nests "saturated".
    ("monounsaturated_fat", re.compile(r"mono[\s-]?unsat", re.IGNORECASE)),
    ("polyunsaturated_fat", re.compile(r"poly[\s-]?unsat", re.IGNORECASE)),
    ("unsaturated_fat", re.compile(r"unsaturat", re.IGNORECASE)),
    ("saturated_fat", re.compile(r"saturat", re.IGNORECASE)),
    ("trans_fat", re.compile(r"trans", re.IGNORECASE)),
    ("cholesterol", re.compile(r"cholesterol", re.IGNORECASE)),
    ("potassium", re.compile(r"potassium", re.IGNORECASE)),
    # "Sugars" and "Dietary Fibre" both sit under carbohydrate on a label.
    ("sugar", re.compile(r"sugar", re.IGNORECASE)),
    ("fiber", re.compile(r"fib(?:re|er)", re.IGNORECASE)),
    ("protein", re.compile(r"protein", re.IGNORECASE)),
    ("carbs", re.compile(r"carb", re.IGNORECASE)),
    ("fat", re.compile(r"fat", re.IGNORECASE)),
    ("kcal", re.compile(r"energy|kilojoule|calorie", re.IGNORECASE)),
)


def _named_rows() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Every wire name no rule above claims, matched as a label spells it.

    The vitamins and minerals, in practice. The spelling is the library's, so
    a name added upstream is read here without an edit; the order is ours:
    longest first, so "Vitamin B12" cannot be claimed by a shorter neighbour,
    then alphabetical, so a set's iteration order never decides a tie.
    """
    claimed = {key for key, _ in _HAND_WRITTEN}
    names = sorted(
        set(NUTRIENTS) - claimed, key=lambda name: (-len(name), name)
    )
    return tuple(
        (name, re.compile(row_pattern(name), re.IGNORECASE)) for name in names
    )


# Appended, never inserted: the guarantees above need those rules tried first.
_ROWS: tuple[tuple[str, re.Pattern[str]], ...] = _HAND_WRITTEN + _named_rows()


class NutritionError(ValueError):
    """A panel that is not worth storing, or a declaration that conflicts."""


def _quantities(text: str) -> list[tuple[float, str]]:
    """Every number on a line, with whatever unit was written beside it."""
    found = []
    for match in _QUANTITY.finditer(text):
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        found.append((value, (match.group(2) or "").lower()))
    return found


def energy_to_kcal(value: float, unit: str) -> float:
    """Normalize an energy figure to calories, whichever unit was used.

    The conversion is exact and the float is taken at the end, because a
    record still holds floats: this is where the lossy domain begins.
    """
    if unit.lower() != "kj":
        return value
    return float(kcal_from_kj(value))


def _row_key(label: str) -> str | None:
    for key, pattern in _ROWS:
        if pattern.search(label):
            return key
    return None


def _in_grams(key: str, chosen: tuple[float, str]) -> float:
    """One row's figure as the grams a record stores.

    A macro is only ever printed in grams, so a bare "Protein 8.5" is not
    ambiguous. Every other nutrient is printed in whichever unit keeps it
    legible, so a bare number there is a guess between answers 1000x apart.
    Rounded because dividing leaves float noise a record would carry verbatim.
    """
    value, unit = chosen

    if key not in CORE_NUTRIENTS and not unit:
        raise NutritionError(
            f"nutrition panel states {key} with no unit: write"
            f" {value:g}g or {value:g}mg"
        )

    divisor = _UNITS_PER_GRAM.get(unit)
    return round(value / divisor, GRAM_PLACES) if divisor else value


def panel_from_rows(rows: list[tuple[str, str]]) -> dict[str, float]:
    """Read a panel whose rows a source already separated for us.

    Rendering a structured table back into label text only to hunt the name
    out of it again invents an ambiguity that was never in the data: it is
    what lets an ingredient list reach these patterns at all. Names are
    matched whole here, and the figures come straight across.
    """
    panel: dict[str, float] = {}

    for name, value in rows:
        key = "sodium" if _SODIUM_NAME.match(name) else _row_key(name)
        if key is None or key == "skip":
            continue

        found = [q for q in _quantities(value) if math.isfinite(q[0])]
        if not found:
            continue

        if key == "kcal":
            _read_energy(panel, found)
            continue

        figure, unit = found[0]
        named = _NAME_UNIT.search(name)
        panel[key] = _in_grams(
            key, (figure, unit or (named.group(1).lower() if named else ""))
        )

    return panel


def _read_energy(
    panel: dict[str, float], found: list[tuple[float, str]]
) -> None:
    """Energy is the one row that can carry two units in a single column.

    A label writing "1000kJ (239Cal)" already did the arithmetic, and its own
    calorie figure beats converting the kilojoules ourselves. Kilojoules are
    converted here and not carried: a record holds kcal, and a second spelling
    of the same figure is one more thing that can disagree with itself.
    """
    calories = [q for q in found if q[1] in ("kcal", "cal")]
    value, unit = (calories or found)[0]
    panel["kcal"] = energy_to_kcal(value, unit or "kj")


def nutrients_for_storage(panel: dict[str, float]) -> dict[str, float]:
    """Validate reported values without filling any missing value."""
    for key, value in panel.items():
        if not math.isfinite(value) or value < 0:
            raise NutritionError(f"nutrition panel has invalid {key}: {value}")
        if key == "kcal" and value > _MAX_KCAL_PER_100G:
            raise NutritionError(f"nutrition panel has invalid kcal: {value}")
        if key != "kcal" and value > 100:
            raise NutritionError(f"nutrition panel has invalid {key}: {value}")

    macro_vals = [
        panel[key] for key in ("protein", "fat", "carbs") if key in panel
    ]
    if len(macro_vals) == 3 and sum(macro_vals) > _MASS_TOLERANCE:
        raise NutritionError("nutrition panel has more than 100 g of macros")
    return panel
