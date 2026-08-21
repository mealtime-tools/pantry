"""Reading a nutrition panel, from a site's data or from text a user pasted.

Everything downstream of this file is per 100 g, and everything upstream of it
is a label written for humans: two columns, trace amounts written as a bound,
energy in kilojoules, sub-rows indented under their parent. This is where that
becomes numbers, and where a panel that did not parse is refused.
"""

import math
import re
from typing import Any

_KJ_PER_KCAL = 0.239006

# No food exceeds pure fat, which is 900 kcal per 100 g.
_MAX_KCAL_PER_100G = 900

# Rounding on a label lets the three macros total slightly over 100 g.
_MASS_TOLERANCE = 105

_QUANTITY = re.compile(
    r"(-?[\d,]+(?:\.\d+)?)\s*(kcal|cal|kj|mg|g|ml)?\b", re.IGNORECASE
)

# The rows this parser recognizes, in the order it tries them. Sub-rows come
# first: "- Saturated" would otherwise match the fat row, and "Sugars" and
# "Dietary Fibre" both sit under carbohydrate on a label.
_ROWS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "skip",
        re.compile(
            r"saturat|trans|monounsat|polyunsat|sodium|salt"
            r"|cholesterol|potassium",
            re.IGNORECASE,
        ),
    ),
    ("sugar", re.compile(r"sugar", re.IGNORECASE)),
    ("fiber", re.compile(r"fib(?:re|er)", re.IGNORECASE)),
    ("protein", re.compile(r"protein", re.IGNORECASE)),
    ("carbs", re.compile(r"carb", re.IGNORECASE)),
    ("fat", re.compile(r"fat", re.IGNORECASE)),
    ("kcal", re.compile(r"energy|kilojoule|calorie", re.IGNORECASE)),
)

# The units a pack or serving size is written in, at the end of the figure.
_UNIT = re.compile(r"(kg|ml|l|g)\s*$", re.IGNORECASE)

_PER_HUNDRED = re.compile(r"per\s*100\s*(?:g|ml)", re.IGNORECASE)
_PER_SERVING = re.compile(r"per\s*serv", re.IGNORECASE)


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


def parse_quantity(text: str | None) -> float | None:
    """Read a single figure off a label.

    A trace amount is written as a bound (`< 1.0g`, `LESS THAN 1.0 g`) and
    the bound is the only figure the label carries, so it is what is stored.
    """
    if not text:
        return None

    found = _quantities(text)
    return found[0][0] if found else None


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

    return (parse_quantity(text), match.group(1).lower())


def energy_to_kcal(value: float, unit: str) -> float:
    """Normalize an energy figure to calories, whichever unit was used."""
    return value * _KJ_PER_KCAL if unit.lower() == "kj" else value


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

        found = [q for q in _quantities(line) if math.isfinite(q[0])]
        if not found:
            continue

        if key == "kcal":
            _read_energy(panel, found, first)
            continue

        chosen = _column(found, first)
        if chosen:
            panel[key] = chosen[0]

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
    calories = [q for q in found if q[1] in ("kcal", "cal")]
    chosen = _column(calories or found, first)
    if not chosen:
        return

    value, unit = chosen[0], chosen[1] or "kj"
    panel["kcal"] = energy_to_kcal(value, unit)
    if unit == "kj":
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

    for key in ("protein", "fat", "carbs"):
        _check_mass(panel, key)

    # Absent is fine (plenty of labels omit both) but present and wrong is
    # not.
    for key in ("fiber", "sugar"):
        if panel.get(key) is not None:
            _check_mass(panel, key)

    # Catches the two mistakes a per-100 g figure cannot survive: a
    # per-serving column read by mistake, and a milligram figure landing in a
    # gram field.
    mass = panel["protein"] + panel["fat"] + panel["carbs"]
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
    # nutrition that was actually printed.
    for key, value in panel.items():
        if value is not None and (not math.isfinite(value) or value != 0):
            raise NutritionError(
                f"--zero-calorie conflicts with nutrition panel {key}: {value}"
            )

    return {"kcal": 0, "protein": 0, "fat": 0, "carbs": 0}
