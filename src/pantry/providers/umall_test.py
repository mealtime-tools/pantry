"""Live Umall search, with its network boundary kept outside the tests."""

import json
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from pantry.open_food_facts import RemoteFailure
from pantry.providers.umall import UmallProvider


def product(**overrides: object) -> dict:
    """One product in the shape the suggest endpoint returns it."""
    row: dict[str, object] = {
        "id": 9056470237471,
        "title": "Ever Green Smooth Strip Tofu, 250g",
        "vendor": "Ever Green",
        "type": "Soy Products",
        "price": "2.39",
        "available": True,
        "url": "/products/fresh-ever-green-smooth-strip-tofu-250g",
    }
    row.update(overrides)
    return row


def response(*products: dict) -> str:
    return json.dumps({"resources": {"results": {"products": list(products)}}})


class TestSearch:
    """A live offer is ranked and priced, but never stored as a panel."""

    def test_a_product_becomes_a_price_result(self) -> None:
        provider = UmallProvider(lambda _: response(product()))

        [result] = provider.search("tofu", 10)

        assert result == {
            "id": "9056470237471",
            "name": "Ever Green Smooth Strip Tofu, 250g",
            "title": "Ever Green Smooth Strip Tofu, 250g (Ever Green)",
            "brand": "Ever Green",
            "grams": 100,
            "source": "umall",
            "price": Decimal("2.39"),
            "currency": "AUD",
            "pack_grams": Decimal("250"),
            "price_per_100g": Decimal("0.956"),
            "available": True,
            "url": "https://www.umall.com.au/products/"
            "fresh-ever-green-smooth-strip-tofu-250g",
            "match": {"score": Decimal("1.00"), "tier": "unknown"},
        }

    def test_an_absolute_product_url_is_kept(self) -> None:
        url = "https://example.test/products/tofu"
        provider = UmallProvider(lambda _: response(product(url=url)))

        [result] = provider.search("tofu", 10)

        assert result["url"] == url

    def test_an_unweighed_product_has_no_unit_price(self) -> None:
        provider = UmallProvider(
            lambda _: response(product(title="Fresh Papaya - 1 Piece"))
        )

        [result] = provider.search("papaya", 10)

        assert result["pack_grams"] is None
        assert result["price_per_100g"] is None

    def test_non_food_and_incomplete_offers_are_ignored(self) -> None:
        provider = UmallProvider(
            lambda _: response(
                product(type="Face Care"),
                product(id=2, title=""),
                product(id=3, price=None),
            )
        )

        assert provider.search("tofu", 10) == []

    def test_results_are_ranked_and_limited_locally(self) -> None:
        provider = UmallProvider(
            lambda _: response(
                product(id=1, title="Silken Tofu 250g"),
                product(id=2, title="Tofu Pudding 250g"),
                product(id=3, title="Fresh Tofu 250g"),
            )
        )

        results = provider.search("silken tofu", 2)

        assert results[0]["id"] == "1"
        assert len(results) == 2

    def test_search_is_a_remote_operation(self) -> None:
        assert UmallProvider.remote


class TestRequest:
    """The suggest request states the query and product-only limit exactly."""

    def test_query_and_limit_are_encoded(self) -> None:
        seen: list[str] = []

        def fetch(url: str) -> str:
            seen.append(url)
            return response()

        UmallProvider(fetch).search("soy milk", 7)

        [url] = seen
        assert "%5B" in url and "%5D" in url
        assert parse_qs(urlparse(url).query) == {
            "q": ["soy milk"],
            "resources[type]": ["product"],
            "resources[limit]": ["7"],
        }

    def test_the_endpoint_limit_is_not_exceeded(self) -> None:
        seen: list[str] = []

        def fetch(url: str) -> str:
            seen.append(url)
            return response()

        UmallProvider(fetch).search("tofu", 200)

        query = parse_qs(urlparse(seen[0]).query)
        assert query["resources[limit]"] == ["10"]


class TestFailure:
    """Network refusals are reported once and malformed results stay empty."""

    def test_an_unreachable_store_is_a_remote_failure(self) -> None:
        calls = 0

        def fetch(_: str) -> str:
            nonlocal calls
            calls += 1
            raise OSError("connection refused")

        with pytest.raises(RemoteFailure, match="could not be reached"):
            UmallProvider(fetch).search("tofu", 10)

        assert calls == 1

    def test_a_response_that_is_not_json_is_a_remote_failure(self) -> None:
        provider = UmallProvider(lambda _: "<html>maintenance</html>")

        with pytest.raises(RemoteFailure, match="not JSON"):
            provider.search("tofu", 10)

    def test_a_response_without_products_is_an_empty_result(self) -> None:
        provider = UmallProvider(lambda _: json.dumps({"resources": {}}))

        assert provider.search("tofu", 10) == []
