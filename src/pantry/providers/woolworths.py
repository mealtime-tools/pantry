"""Woolworths: a live shelf, read through a browser because nothing else may.

The session is opened on the first query and reused for the rest, because
launching costs about four seconds and a recipe asks twenty times. It is
opened lazily so a run that never searches Woolworths never starts a browser.
"""

from collections.abc import Callable
from typing import Any, Protocol

from pantry.open_food_facts import RemoteFailure
from pantry.providers import Provider
from pantry.woolworths import SOURCE, read_search


class SearchSession(Protocol):
    """An open browser, or a test double with the same two methods."""

    def results(self, query: str) -> Any:
        """Return the payload the site's own search request answered with."""

    def close(self) -> None:
        """Release the browser."""


class WoolworthsProvider(Provider):
    """Search the shelf. The panel is a `pantry add` on the result's ref."""

    name = SOURCE
    searchable = True

    def __init__(self, open_session: Callable[[], SearchSession]) -> None:
        self._open_session = open_session
        self._session: SearchSession | None = None

    def search(self, query: str, limit: int) -> list[dict]:
        return read_search(self._opened().results(query), limit)

    def _opened(self) -> SearchSession:
        """The running session, starting one the first time it is needed."""
        if self._session is None:
            try:
                self._session = self._open_session()
            except Exception as cause:  # noqa: BLE001 - playwright's own types
                raise RemoteFailure(
                    f"Woolworths search needs a browser: {cause}"
                ) from None

        return self._session

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
