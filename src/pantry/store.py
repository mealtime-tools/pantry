"""The user's own records, laid over the frozen shards.

They live under the user's config directory and **never** inside a checkout:
the base shards cannot be regenerated, so promoting a record into one is a
deliberate copy, not something a fetch does. Both halves share one layout, a
directory of `<source>.jsonl` shards taking their source from the filename, so
there is no second parser to drift.
"""

import os
from collections.abc import Callable, Mapping
from pathlib import Path

from pantry.data import read_shard, read_shards
from pantry.local import Local
from pantry.products import (
    Product,
    assert_exportable_product,
    format_jsonl,
    identity,
)


def store_dir(
    env: Mapping[str, str] | None = None, home: Path | None = None
) -> Path:
    """Where a user's own records live, following the XDG convention.

    A directory rather than a file: one shard per source, exactly as the
    frozen data ships, so `read_shards` serves both.
    """
    environ = os.environ if env is None else env
    config = environ.get("XDG_CONFIG_HOME")
    base = Path(config) if config else (home or Path.home()) / ".config"
    return base / "pantry"


def write_atomic(path: Path, text: str) -> None:
    """Write a file whole, atomically.

    A torn write would cost the user page loads they cannot get back, so the
    rename is what makes the new content visible.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


class Store:
    """Everything the user can search: the frozen shards plus their records.

    The base arrives as a callable for the same reason `Local` takes a list —
    the CLI reads files, a test hands over three dicts, and neither has to know
    about the other.
    """

    def __init__(
        self, load_base: Callable[[], list[Product]], store: Path
    ) -> None:
        self._load_base = load_base
        self._store = store
        self._base: list[Product] | None = None

    def base(self) -> list[Product]:
        """Cached, because it is a 3 MB read that never changes mid-run."""
        if self._base is None:
            self._base = self._load_base()
        return self._base

    def all(self) -> list[Product]:
        """Both halves as one list, the user's own winning on identity.

        Merging is per `(source, id)`, not per file: a `coles.jsonl` in the
        store shadows individual rows of the shipped shard, never the whole
        of it.
        """
        merged = {identity(p): p for p in self.base()}
        for product in read_shards(self._store):
            merged[identity(product)] = product
        return list(merged.values())

    def find(self, source: str, product_id: str) -> Product | None:
        """One exact source-and-id pair.

        This is the check that stands between the user and a wasted page load,
        so it reads the store from disk rather than trusting a cache.
        """
        return Local(self.all()).find(source, product_id)

    def add(self, product: Product) -> None:
        """Store a newly acquired product, immediately and durably."""
        assert_exportable_product(product)
        self._write(product)

    def _write(self, product: Product) -> None:
        """Land a record in the shard named for its source.

        Rewritten whole rather than appended, because a shard is sorted with
        a fixed key order.
        """
        source = product["source"]
        shard = self._store / f"{source}.jsonl"

        held = read_shard(shard, source)
        kept = [p for p in held if identity(p) != identity(product)]
        write_atomic(shard, format_jsonl([*kept, product], source=source))

    def stored(self, source: str, product_id: str) -> Product | None:
        """Only the user's own copy, ignoring the frozen shards.

        What may be deleted is exactly this: a shipped row is not the user's
        to remove, and a correction that shadows one is.
        """
        return Local(read_shards(self._store)).find(source, product_id)

    def remove(self, source: str, product_id: str) -> bool:
        """Drop the user's own record, if the store holds one.

        The shard is rewritten whole for the same reason `_write` does it, and
        an emptied one is left in place rather than unlinked: an empty shard
        and an absent shard read identically.
        """
        shard = self._store / f"{source}.jsonl"
        held = read_shard(shard, source)
        kept = [p for p in held if identity(p) != (source, product_id)]
        if len(kept) == len(held):
            return False

        write_atomic(shard, format_jsonl(kept, source=source))
        return True

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Fuzzy search over both halves.

        A fresh index per query, so a product added a moment ago is findable;
        rebuilding it over twelve thousand rows is far cheaper than the page
        load this search exists to avoid.
        """
        return Local(self.all()).search(query, limit=limit)
