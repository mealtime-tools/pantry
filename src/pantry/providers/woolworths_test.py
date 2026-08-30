"""Driving a Woolworths search without opening a browser."""

from typing import Any

import pytest

from pantry.open_food_facts import RemoteFailure
from pantry.providers.woolworths import WoolworthsProvider
from pantry.woolworths_test import BEGA, FETTA, payload


class FakeSession:
    """Stands in for the browser: the same one method, and a close."""

    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.asked: list[str] = []
        self.closed = False

    def results(self, query: str) -> Any:
        self.asked.append(query)
        return self.answer

    def close(self) -> None:
        self.closed = True


def provider(session: FakeSession) -> WoolworthsProvider:
    return WoolworthsProvider(lambda: session)


def test_a_search_returns_every_offer_the_shop_answered_with() -> None:
    """Kept whole and in order: the shop's relevance is the ranking."""
    session = FakeSession(payload(BEGA, FETTA))

    found = provider(session).search("cheese", 10)

    assert [row["id"] for row in found] == ["6026666", "6027911"]


def test_the_browser_opens_once_and_answers_every_query() -> None:
    """A recipe is twenty ingredients; a launch costs four seconds."""
    session = FakeSession(payload(BEGA))
    reader = provider(session)

    reader.search("cheese", 10)
    reader.search("fetta", 10)

    assert session.asked == ["cheese", "fetta"]


def test_nothing_is_opened_until_something_is_searched_for() -> None:
    opened: list[int] = []

    WoolworthsProvider(lambda: opened.append(1) or FakeSession({}))

    assert opened == []


def test_closing_releases_the_browser() -> None:
    session = FakeSession(payload(BEGA))
    reader = provider(session)
    reader.search("cheese", 10)

    reader.close()

    assert session.closed


def test_closing_an_unopened_provider_is_not_an_error() -> None:
    provider(FakeSession({})).close()


def test_a_browser_that_cannot_start_says_so() -> None:
    def refuse() -> Any:
        raise RuntimeError("no chrome here")

    with pytest.raises(RemoteFailure, match="Woolworths search needs"):
        WoolworthsProvider(refuse).search("cheese", 10)


def test_the_provider_is_a_searchable_network_source() -> None:
    assert WoolworthsProvider.searchable
    assert not WoolworthsProvider.acquirable
