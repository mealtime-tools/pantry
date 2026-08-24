"""Validate structured nutrition rows from retailer and database sources.

Everything returned by this file is grams per 100 g, and everything upstream
of it is a row whose source already separated its name from its value.
"""

import math
import re

from mealtime_nutrients import CORE_NUTRIENTS, NUTRIENTS, kcal_from_kj

# A label prints its mineral rows in milligrams and its vitamin rows in
# micrograms; a record holds grams. This is the only place those units meet,
# because it is the only place a unit is read off a human-written line.
_UNITS_PER_GRAM = {
    "mg": 1000,
    "mcg": 1_000_000,
    "µg": 1_000_000,
    "μg": 1_000_000,
}

# Places enough to hold a converted microgram: 2.4 µg is 2.4e-06 g, which six
# places would quantise to a figure reading 17 percent low.
GRAM_PLACES = 12

# No food exceeds pure fat, which is 900 kcal per 100 g.
_MAX_KCAL_PER_100G = 900

# Rounding on a label lets the three macros total slightly over 100 g.
_MASS_TOLERANCE = 105

# Both spellings of micro are listed: the micro sign and the Greek mu look
# identical and labels are copied from both. Without them the trailing \b
# backtracks into the number and "1.2µg" reads as a bare 1.0.
_QUANTITY = re.compile(
    r"(-?[\d,]+(?:\.\d+)?)\s*(kcal|cal|kj|mcg|µg|μg|mg|g|ml)?\b",
    re.IGNORECASE,
)

# The sodium row, and only the sodium row: the word opens the line and its
# figure follows immediately, with nothing between but the "less than" a trace
# amount is printed as. Anchored and adjacent so that an ingredient list
# naming sodium -- "Sodium Bicarbonate (500)" -- falls through to the skip rule
# instead. A row this does not recognize reads as absent, which is the safe
# answer: a missing sodium is unknown by contract, a wrong one is not.
_SODIUM_ROW = re.compile(
    r"^\s*sodium\b:?\s*(?:less\s+than\s+)?[<\d]", re.IGNORECASE
)

# The same row, named rather than hunted for. A structured source states its
# nutrient names, so the figure it must be followed by in pasted text -- the
# thing that keeps "Sodium Bicarbonate (500)" out of a record -- is not needed
# and would not be there to match.
_SODIUM_NAME = re.compile(r"^\s*sodium\b[\s(]*(?:mg|g)?\)?\s*$", re.IGNORECASE)

# A structured source often puts the unit in the row name -- "Sodium (mg)"
# against a bare 400 -- which is the same figure stated a different way, not a
# missing unit.
_NAME_UNIT = re.compile(r"\(?\b(mcg|µg|μg|mg|g)\b\)?\s*$", re.IGNORECASE)

# The rows this parser recognizes, in the order it tries them. First match
# wins, and every rule below sits where it does because a later one would
# otherwise claim the row: a sub-row before the total it sits under, and the
# skip rule before the row whose word it accidentally contains.
_ROWS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Read, unlike the salt row below it: salt is 2.5 times its sodium, so
    # taking one for the other would overstate the figure by 150 percent.
    ("sodium", _SODIUM_ROW),
    # Salt is not sodium, and any other line naming sodium is not the sodium
    # row -- "Sodium Bicarbonate (500)" would reach *carbs* on "bicarbonate".
    ("skip", re.compile(r"sodium|salt", re.IGNORECASE)),
    # The fat sub-rows, longest name first: "polyunsaturated" contains
    # "unsaturated", which contains "saturated". A bare "- Saturated" names no
    # fat at all, so only the order keeps it off the total below.
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

# The vitamins and minerals, whose row names are their wire names with a space
# for the underscore. Derived so a name added upstream is read here too, and
# longest first so "Vitamin B12" cannot be claimed by a shorter neighbour.
_UNCOVERED: set[str] = (
    set(NUTRIENTS) - {key for key, _ in _ROWS} - set(CORE_NUTRIENTS)
)

_DERIVED_ROWS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(name.replace("_", r"[\s-]?"), re.IGNORECASE))
    for name in sorted(_UNCOVERED, key=lambda name: -len(name))
)

# Appended, never inserted: every ordering guarantee above depends on the
# hand-written rules being tried first.
_ROWS = _ROWS + _DERIVED_ROWS


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
    """Normalize an energy figure to calories, whichever unit was used."""
    return kcal_from_kj(value) if unit.lower() == "kj" else value


def _row_key(label: str) -> str | None:
    for key, pattern in _ROWS:
        if pattern.search(label):
            return key
    return None


def _in_grams(key: str, chosen: tuple[float, str]) -> float:
    """One row's figure as the grams a record stores.

    A macro is only ever printed in grams, so a bare "Protein 8.5" is not
    ambiguous. Every other nutrient is printed in whichever unit keeps it
    legible -- sodium in milligrams, the same figure in grams a thousandth of
    the size -- so a bare number there is a guess between two answers that
    differ by 1000x, and refusing beats guessing. Rounded because dividing
    leaves binary-float noise that would be written to the record verbatim.
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

    An API's nutrition table gives a name and a figure per row, so rendering
    those back into label text only to hunt the name out of it again invents
    an ambiguity that was never in the data: it is what lets an ingredient
    list reach these patterns at all. Names are matched whole here, and the
    figures come straight across.
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
