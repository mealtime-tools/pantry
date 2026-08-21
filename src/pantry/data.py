"""Where the frozen shards live, and how they are read.

`coles.jsonl` holds 10,297 rows from a scrape that took weeks of manual
captcha-solving and no longer exists. Nothing in this package writes to this
directory: it is source data, not a cache. Records the user adds go to their
own store under XDG config, in this same one-shard-per-source layout, and
promoting one into here is a deliberate copy a human diffs and commits.
"""

import os
from collections.abc import Mapping
from pathlib import Path

from pantry.products import PRODUCT_SOURCES, Product, parse_jsonl

DATA_ENV = "PANTRY_DATA_DIR"


def _owned_data() -> Path:
    """Find the same owned shards in a wheel or source checkout."""
    packaged = Path(__file__).resolve().parent / "data"
    if packaged.is_dir():
        return packaged

    return Path(__file__).resolve().parents[2] / "data"


# `coles.jsonl` cannot be regenerated, so nothing writes to this directory.
_PACKAGE_DATA = _owned_data()


def data_dir(env: Mapping[str, str] | None = None) -> Path:
    """The directory holding the canonical per-source shards."""
    environ = os.environ if env is None else env
    override = environ.get(DATA_ENV)
    return Path(override) if override else _PACKAGE_DATA


def read_shard(path: Path, source: str) -> list[Product]:
    """Read one shard, treating "not written yet" as "empty".

    The source comes from the caller rather than the rows, because the
    filename is what records it.
    """
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    return parse_jsonl(text, source=source, label=str(path))


def read_shards(directory: Path) -> list[Product]:
    """Read every source shard present, taking each row's source from its name.

    A missing shard is not an error: a directory may legitimately carry only
    some of them, and search over what is there beats refusing to start. This
    serves the shipped data and the user's own store alike.
    """
    products: list[Product] = []
    for source in PRODUCT_SOURCES:
        products.extend(read_shard(directory / f"{source}.jsonl", source))

    return products
