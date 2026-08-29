"""Reading the Open Food Facts CSV export, one line at a time.

A catalogue refresh leaves tens of thousands of barcodes with no panel, and
asking the public index for them one at a time is refused long before the end:
it allows about ten searches a minute. The export answers all of them in one
download instead.

The CSV is chosen over the JSONL for its size — 1.3 GB against 12.8 GB, for
the same rows and every column this needs. It is tab-separated and unquoted,
so a quote inside a product name is data rather than a delimiter.

`stream` is the only function here that touches the network. Everything below
it takes lines and returns rows, so the parsing, the diet and the record shape
are all tested offline against a handful of literal lines.
"""

import csv
import gzip
import io
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from pantry.nutrition import NutritionError, nutrients_for_storage
from pantry.open_food_facts import RemoteFailure
from pantry.products import Product
from pantry.sites import build_record

DUMP_URL = (
    "https://static.openfoodfacts.org/data/"
    "en.openfoodfacts.org.products.csv.gz"
)

# The export's own column names, and what a record calls them.
_NUTRIENTS = {
    "kcal": "energy-kcal_100g",
    "protein": "proteins_100g",
    "fat": "fat_100g",
    "carbs": "carbohydrates_100g",
    "fiber": "fiber_100g",
    "sugar": "sugars_100g",
    # Already grams per 100 g in the export, which is what a record holds.
    "sodium": "sodium_100g",
}

# What the export concludes from an ingredient list, in the order that a
# stricter answer wins: a vegan product is also a vegetarian one.
_DIETS = (
    ("vegan", "en:vegan"),
    ("vegetarian", "en:vegetarian"),
    ("non-vegetarian", "en:non-vegetarian"),
)

PRODUCT_URL = "https://world.openfoodfacts.org/product/{}"

_USER_AGENT = "pantry/0.1 (https://github.com/mealtime-tools/pantry)"


def stream(url: str = DUMP_URL) -> Iterator[str]:
    """The export as text lines, decompressed as it arrives.

    Never written to disk: at 1.3 GB compressed there is no reason to land it,
    and the one pass that reads it does not need to go back. `errors` is
    replace because a single undecodable byte in one product name must not
    end a download that takes minutes.
    """
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except OSError as exc:
        raise RemoteFailure(
            f"the Open Food Facts export could not be read: {exc}"
        ) from None

    with response:
        unzipped = gzip.GzipFile(fileobj=response)
        yield from io.TextIOWrapper(
            unzipped, encoding="utf-8", errors="replace", newline=""
        )


def _figure(value: str) -> Decimal | None:
    """One nutrient cell: a number the export stated, or nothing.

    Six places for the same reason the index reader keeps six: a trace mineral
    is thousandths of a gram, and fewer would round it to a zero that reads as
    "none of it" rather than "hardly any".
    """
    text = value.strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    if not parsed.is_finite() or parsed < 0:
        return None

    return round(parsed, 6)


def rows(lines: Iterable[str]) -> Iterator[dict[str, str]]:
    """Every data line as a mapping, taking the field names from the first.

    Unquoted on purpose: the export does not quote, so letting the reader
    treat a quote as a delimiter would swallow the rest of a product name.
    """
    reader = csv.reader(lines, delimiter="\t", quoting=csv.QUOTE_NONE)
    try:
        header = next(reader)
    except StopIteration:
        return

    for fields in reader:
        # A short or long line is skipped rather than guessed at: the export
        # is 211 columns wide and a row that is not is a truncated one.
        if len(fields) != len(header):
            continue
        yield dict(zip(header, fields, strict=True))


def diet(row: dict[str, str]) -> str | None:
    """What the export concluded about this product's ingredients.

    Absent where it could not tell, which is most of them: an unknown status
    is not a licence to call something vegetarian.

    Matched whole, never as a substring. The export spells "we could not tell"
    as `en:vegan-status-unknown`, which contains `en:vegan` and would
    otherwise label the most uncertain rows as the strictest answer.
    """
    tags = {
        tag.strip()
        for tag in (row.get("ingredients_analysis_tags") or "").split(",")
    }
    return next((name for name, tag in _DIETS if tag in tags), None)


def record(row: dict[str, str]) -> Product | None:
    """One export row as a stored record, or nothing.

    Refused where there is nothing to store: a row with no barcode has no
    identity, no name has nothing to show a user, and no nutrient at all is
    not a panel. A panel missing some of its figures is kept, because a
    partial answer is still an answer.
    """
    barcode = (row.get("code") or "").strip()
    name = (row.get("product_name") or "").strip()
    if not barcode or not name:
        return None

    panel = {
        key: figure
        for key, column in _NUTRIENTS.items()
        for figure in (_figure(row.get(column, "")),)
        if figure is not None
    }
    if not panel:
        return None

    try:
        checked = nutrients_for_storage(panel)
    except NutritionError:
        # The export is community-maintained and carries rows stating things
        # like 6380 kcal per 100 g. One of those must not end a download that
        # takes minutes, so it is dropped rather than raised.
        return None

    return build_record(
        source="openfoodfacts",
        product_id=barcode,
        name=name,
        brand=(row.get("brands") or "").strip(),
        panel=checked,
        url=PRODUCT_URL.format(barcode),
    )


@dataclass(frozen=True)
class Harvest:
    """What one pass over the export found for the barcodes asked about.

    `matched` counts the rows the export held, `records` only those it held a
    usable panel for. Reporting one number would hide which of the two a
    barcode failed at: absent from the export, or present and unusable.
    """

    records: list[Product]
    diets: dict[str, str]
    matched: int


def harvest(lines: Iterable[str], wanted: set[str]) -> Harvest:
    """The records and diets for the barcodes asked about, and no others.

    One pass, because the export is read as it downloads and there is no
    second chance at a line. Both halves come back together for that reason:
    two passes would mean two downloads.
    """
    found: list[Product] = []
    diets: dict[str, str] = {}
    matched: set[str] = set()

    for row in rows(lines):
        barcode = (row.get("code") or "").strip()
        if barcode not in wanted:
            continue

        matched.add(barcode)
        status = diet(row)
        if status is not None:
            diets[barcode] = status

        product = record(row)
        if product is not None:
            found.append(product)

    return Harvest(found, diets, len(matched))
