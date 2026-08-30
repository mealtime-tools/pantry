"""What the Coles provider asks for, and what it makes of the answer."""

import json

import pytest

from pantry.coles_test import PAYLOAD
from pantry.providers.coles import ColesProvider
from pantry.sites import SiteError


def page(payload: dict) -> str:
    body = json.dumps({"props": {"pageProps": payload}})
    return (
        f'<script id="__NEXT_DATA__" type="application/json">{body}</script>'
    )


def test_the_shelf_is_a_plain_request_and_a_search_source() -> None:
    assert ColesProvider.searchable
    assert not ColesProvider.acquirable


def test_a_query_is_asked_of_the_ordinary_search_url() -> None:
    seen: list[str] = []

    def load(url: str) -> str:
        seen.append(url)
        return page(PAYLOAD)

    ColesProvider(load).search("bega protein cheese", limit=5)

    assert seen == [
        "https://www.coles.com.au/search/products?q=bega+protein+cheese"
    ]


def test_the_payload_becomes_offers() -> None:
    found = ColesProvider(lambda _: page(PAYLOAD)).search("cheese", limit=5)

    assert [result["id"] for result in found] == ["1145381", "7699284"]


def test_a_page_that_is_not_the_search_page_is_refused() -> None:
    """An interstitial that got past the block markers is not results.

    The reason travels as it was raised: the loader already says a site
    declined, and restating that here would only bury which rule stopped it.
    """
    with pytest.raises(SiteError):
        ColesProvider(lambda _: "<html>nothing here</html>").search("x", 5)
