"""The frozen shards plus the user's own localstore. No network, ever.

Always enabled and always first: this is the check that stands between the
user and a page load they cannot get back.
"""

from pantry.providers import Provider
from pantry.store import Store


class LocalProvider(Provider):
    """Fuzzy search over everything already held."""

    name = "local"
    searchable = True

    def __init__(self, store: Store) -> None:
        self._store = store

    def search(self, query: str, limit: int) -> list[dict]:
        return self._store.search(query, limit=limit)
