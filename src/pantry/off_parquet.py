"""Reading the Open Food Facts parquet export with DuckDB.

The CSV export is the English view of the database and the smaller download,
but it flattens away two things this needs. A product whose name is only in
Japanese has an empty `product_name` there, and its ingredient analysis
arrives as one comma-joined string that has to be split back apart. The
parquet keeps both as they are: names are a list of `(lang, text)` and the
analysis is already a list of tags.

It is also the whole database rather than a language view, which is where the
records the CSV never mentions come from.

It is downloaded whole rather than queried where it sits. Hugging Face
rate-limits the hundreds of small range requests a remote parquet read makes
and refuses the read partway through with a 429; it also shapes a plain
download to a few MB/s. Measured against this file: `hf` fetches it at about
45 MB/s where `curl` manages 2.4, because it splits the file across parallel
chunked requests instead of holding one connection. So `hf` is used when it
is installed and `curl` is the fallback — slow, but it finishes and resumes.

The file is then a local cache: a second backfill, or a different question
entirely, costs nothing.

A `$HF_TOKEN` is optional and made no measurable difference to the throttle;
it is passed through for the private or rate-limited cases where it would.
For curl it goes in on stdin rather than as an argument, because an argument
is visible to anyone running `ps`.
"""

import os
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from pantry.nutrition import NutritionError, nutrients_for_storage
from pantry.off_dump import PRODUCT_URL, Harvest, _figure
from pantry.open_food_facts import RemoteFailure
from pantry.sites import build_record

# What `hf` needs, and the plain URL curl falls back to. One file, named the
# same in both, so a download lands where the cache expects it either way.
REPO_ID = "openfoodfacts/product-database"
REPO_FILE = "food.parquet"
PARQUET_URL = (
    f"https://huggingface.co/datasets/{REPO_ID}/resolve/main/{REPO_FILE}"
)

# The export's own nutrient names, and what a record calls them. Every figure
# is read from the `100g` field, which is the basis a record is stated in.
_NUTRIENTS = {
    "kcal": "energy-kcal",
    "protein": "proteins",
    "fat": "fat",
    "carbs": "carbohydrates",
    "fiber": "fiber",
    "sugar": "sugars",
    "sodium": "sodium",
}

# Which name to take, in order. A product sold here under a Japanese name is
# still worth holding: the barcode is what identifies it, and a name in the
# wrong script beats no record at all.
_NAME_LANGS = ("en", "main")

# What the analysis concluded, strictest answer first.
_DIETS = (("vegan", "en:vegan"), ("vegetarian", "en:vegetarian"),
          ("non-vegetarian", "en:non-vegetarian"))

_COLUMNS = ", ".join(
    [
        "code",
        *(
            f"list_filter(product_name, x -> x.lang = '{lang}')[1].text "
            f"AS name_{lang}"
            for lang in _NAME_LANGS
        ),
        "product_name[1].text AS name_any",
        "brands",
        "ingredients_analysis_tags AS analysis",
        *(
            f"list_filter(nutriments, n -> n.name = '{column}')[1]['100g'] "
            f"AS {key}"
            for key, column in _NUTRIENTS.items()
        ),
    ]
)


# Roughly what the file weighs, for saying so before spending it.
APPROXIMATE_BYTES = 6_900_000_000

# A read token lifts Hugging Face's throttle on an unauthenticated download.
TOKEN_ENV = "HF_TOKEN"


def _token(env: Mapping[str, str] | None = None) -> str | None:
    """The Hugging Face read token, if the user has one. Never required."""
    if env is None:
        load_dotenv()
        env = os.environ

    return env.get(TOKEN_ENV) or None


def download(path: Path, url: str = PARQUET_URL) -> Path:
    """Fetch the export once, or reuse the copy already here.

    The partial keeps a fixed name so `curl -C -` resumes it on the next run
    rather than starting a seven-gigabyte download again, and the rename is
    what makes a complete file visible: an interrupted one is never mistaken
    for a whole one. Nothing here deletes the finished file — it is the
    user's cache to keep or remove.
    """
    if path.is_file():
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("hf") is not None:
        return _download_hf(path)
    if shutil.which("curl") is None:
        raise RemoteFailure(
            f"downloading the parquet export needs hf or curl; "
            f"fetch {url} yourself and place it at {path}"
        )

    partial = path.with_name(f"{path.name}.part")

    # On stdin, not in argv: a token in an argument is readable from `ps`.
    token = _token()
    config = f'header = "Authorization: Bearer {token}"\n' if token else ""

    finished = subprocess.run(
        # `-C -` resumes, `-fL` fails loudly and follows the CDN redirect.
        ["curl", "-fL", "--retry", "3", "-C", "-", "-o", str(partial),
         "-K", "-", url],
        input=config,
        text=True,
        check=False,
    )
    if finished.returncode != 0:
        raise RemoteFailure(
            f"curl could not download the parquet export "
            f"(exit {finished.returncode}); rerun to resume"
        )

    partial.replace(path)
    return path


def _environment() -> dict[str, str]:
    """The child's environment, carrying the token when one is configured."""
    environment = dict(os.environ)
    if token := _token():
        environment[TOKEN_ENV] = token
    return environment


def _download_hf(path: Path) -> Path:
    """Fetch through the Hugging Face client, which parallelises chunks.

    It writes the file under `--local-dir` by its name in the repository,
    which is the name the cache uses, so nothing has to be moved afterwards.
    Its own bookkeeping directory is removed: it holds the part file during
    the transfer and is worth nothing once the download is whole.
    """
    finished = subprocess.run(
        ["hf", "download", REPO_ID, REPO_FILE, "--repo-type", "dataset",
         "--local-dir", str(path.parent)],
        env=_environment(),
        # `hf` prints the path it wrote to stdout. Under `--json` that is the
        # one stream promised to hold a single object, so it goes nowhere.
        # Its progress bar is on stderr and stays, which is the useful half.
        stdout=subprocess.DEVNULL,
        check=False,
    )
    if finished.returncode != 0:
        raise RemoteFailure(
            f"hf could not download the parquet export "
            f"(exit {finished.returncode}); rerun to resume"
        )

    shutil.rmtree(path.parent / ".cache", ignore_errors=True)
    return path


def _connect():
    """A DuckDB session. The parquet is local, so no http extension."""
    try:
        import duckdb
    except ImportError:  # pragma: no cover - declared as a dependency
        raise RemoteFailure(
            "reading the parquet export needs duckdb"
        ) from None

    return duckdb.connect()


def _name(row: dict[str, Any]) -> str:
    """The first name the product states, in the order the languages rank."""
    for key in (*(f"name_{lang}" for lang in _NAME_LANGS), "name_any"):
        if value := (row.get(key) or "").strip():
            return value
    return ""


def _diet(row: dict[str, Any]) -> str | None:
    """What the analysis concluded, where it concluded anything.

    The tags arrive as a list here, so this is an exact membership test rather
    than the substring match the flattened CSV forces — no risk of reading
    `en:vegan-status-unknown` as `en:vegan`.
    """
    tags = set(row.get("analysis") or ())
    return next((name for name, tag in _DIETS if tag in tags), None)


def harvest(wanted: Iterable[str], path: Path) -> Harvest:
    """Every record and diet the local export holds for these barcodes.

    The barcodes go in as a table rather than a literal list: a semi-join is
    what lets DuckDB skip the row groups none of them fall in, and an `IN`
    list seventeen thousand long is its own problem.
    """
    connection = _connect()
    connection.execute("CREATE TABLE wanted (code VARCHAR)")
    connection.executemany(
        "INSERT INTO wanted VALUES (?)", [(str(c),) for c in wanted]
    )

    query = (
        f"SELECT {_COLUMNS} FROM read_parquet(?) SEMI JOIN wanted USING (code)"
    )
    try:
        cursor = connection.execute(query, [str(path)])
        columns = [description[0] for description in cursor.description]
        rows = [
            dict(zip(columns, values, strict=True))
            for values in cursor.fetchall()
        ]
    except Exception as error:
        raise RemoteFailure(
            f"the parquet export could not be read: {error}"
        ) from None

    return _read(rows)


def _read(rows: list[dict[str, Any]]) -> Harvest:
    """Parquet rows into records and diets, refusing what cannot be held."""
    found = []
    diets: dict[str, str] = {}

    for row in rows:
        code = str(row.get("code") or "").strip()
        if not code:
            continue

        if status := _diet(row):
            diets[code] = status

        name = _name(row)
        # `or ""` would be wrong here: a reported 0 g of fibre is a fact about
        # the product, and falsiness would file it as never measured.
        panel = {
            key: figure
            for key in _NUTRIENTS
            for value in (row.get(key),)
            for figure in (_figure("" if value is None else str(value)),)
            if figure is not None
        }
        if not name or not panel:
            continue

        try:
            checked = nutrients_for_storage(panel)
        except NutritionError:
            # Community data: rows stating 6380 kcal per 100 g exist, and one
            # of them must not end a read that takes minutes.
            continue

        found.append(
            build_record(
                source="openfoodfacts",
                product_id=code,
                name=name,
                brand=str(row.get("brands") or "").strip(),
                panel=checked,
                url=PRODUCT_URL.format(code),
            )
        )

    return Harvest(found, diets, len(rows))
