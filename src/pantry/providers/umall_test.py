"""Sweeping the catalogue, and pricing what a search finds in it."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from pantry.catalog import catalog_path, write_catalog
from pantry.open_food_facts import RemoteFailure
from pantry.providers.umall import Storefront, UmallProvider
from pantry.store import Store

TOFU = {
    "id": "9352792000258",
    "name": "Max Bean Silken Tofu 300g",
    "brand": "Max Bean",
    "price": Decimal("4.29"),
    "currency": "AUD",
    "pack_grams": Decimal("300"),
    "available": True,
    "url": "https://www.umall.com.au/products/max-bean-silken-tofu-300g",
    "ref": "off:9352792000258",
}

# The same product as Open Food Facts holds it: a panel, per 100 g.
HELD = {
    "source": "openfoodfacts",
    "id": "9352792000258",
    "name": "Silken Tofu",
    "brand": "Max Bean",
    "kcal": Decimal("55"),
    "protein": Decimal("5"),
    "fat": Decimal("2.8"),
    "carbs": Decimal("1.9"),
    "grams": 100,
}


def provider(tmp_path: Path, entries: list[dict], held: list[dict]) -> tuple:
    """A provider over a written catalogue and a store holding `held`."""
    path = catalog_path(tmp_path, "umall")
    write_catalog(path, entries, "2026-08-29T09:00:00Z")
    store = Store(lambda: list(held), tmp_path)
    return UmallProvider(store, path), path


class TestEnabled:
    """An unrefreshed clone drops out rather than failing every search."""

    def test_no_catalogue_means_not_enabled(self, tmp_path: Path) -> None:
        store = Store(lambda: [], tmp_path)
        path = catalog_path(tmp_path, "umall")

        assert not UmallProvider(store, path).enabled

    def test_a_catalogue_enables_it(self, tmp_path: Path) -> None:
        umall, _ = provider(tmp_path, [TOFU], [])

        assert umall.enabled

    def test_searching_costs_nothing_so_it_needs_no_remote_flag(self) -> None:
        assert UmallProvider.remote is False


class TestSearch:
    """A row, the panel held for it, and the prices that need both."""

    def test_a_joined_row_carries_panel_and_unit_prices(
        self, tmp_path: Path
    ) -> None:
        umall, _ = provider(tmp_path, [TOFU], [HELD])

        [result] = umall.search("tofu", 10)

        assert result["kcal"] == Decimal("55")
        assert result["protein"] == Decimal("5")
        assert result["price"] == Decimal("4.29")
        assert result["pack_grams"] == Decimal("300")
        assert result["price_per_100g"] == Decimal("1.43")
        assert result["price_per_100kcal"] == Decimal("2.6")
        assert result["price_per_g_protein"] == Decimal("0.286")

    def test_nutrients_are_per_100_grams_not_per_pack(
        self, tmp_path: Path
    ) -> None:
        """`grams` names the basis of the panel; the pack keeps its own key."""
        umall, _ = provider(tmp_path, [TOFU], [HELD])

        [result] = umall.search("tofu", 10)

        assert result["grams"] == 100
        assert result["pack_grams"] == Decimal("300")

    def test_a_price_is_stamped_with_when_it_was_read(
        self, tmp_path: Path
    ) -> None:
        umall, _ = provider(tmp_path, [TOFU], [HELD])

        [result] = umall.search("tofu", 10)

        assert result["price_at"] == "2026-08-29T09:00:00Z"

    def test_an_unjoined_row_is_priced_by_weight_and_nothing_else(
        self, tmp_path: Path
    ) -> None:
        """No panel is held, so no figure is invented to fill one in."""
        umall, _ = provider(tmp_path, [TOFU], [])

        [result] = umall.search("tofu", 10)

        assert "kcal" not in result
        assert result["price_per_100g"] == Decimal("1.43")
        assert result["price_per_100kcal"] is None
        assert result["price_per_g_protein"] is None

    def test_an_unweighed_row_has_no_unit_price(self, tmp_path: Path) -> None:
        piece = {**TOFU, "name": "Papaya - 1 Piece"}
        piece.pop("pack_grams")
        umall, _ = provider(tmp_path, [piece], [])

        [result] = umall.search("papaya", 10)

        assert result["pack_grams"] is None
        assert result["price_per_100g"] is None

    def test_an_in_store_code_is_never_joined(self, tmp_path: Path) -> None:
        """Those digits belong to some other manufacturer's product."""
        internal = {**TOFU, "id": "9202402231777"}
        internal.pop("ref")
        held = {**HELD, "id": "9202402231777"}
        umall, _ = provider(tmp_path, [internal], [held])

        [result] = umall.search("tofu", 10)

        assert "kcal" not in result
        assert "ref" not in result

    def test_a_row_says_where_its_panel_would_come_from(
        self, tmp_path: Path
    ) -> None:
        umall, _ = provider(tmp_path, [TOFU], [])

        [result] = umall.search("tofu", 10)

        assert result["ref"] == "off:9352792000258"

    def test_matching_nothing_is_an_empty_list(self, tmp_path: Path) -> None:
        umall, _ = provider(tmp_path, [TOFU], [HELD])

        assert umall.search("bratwurst", 10) == []

    def test_the_limit_is_honoured(self, tmp_path: Path) -> None:
        rows = [{**TOFU, "id": f"935279200025{n}"} for n in range(5)]
        umall, _ = provider(tmp_path, rows, [])

        assert len(umall.search("tofu", 2)) == 2


class TestSweep:
    """Every page, and the refusals that are not worth a second request."""

    def page(self, nodes: list[dict], cursor: str | None) -> dict:
        return {
            "data": {
                "products": {
                    "pageInfo": {
                        "hasNextPage": cursor is not None,
                        "endCursor": cursor,
                    },
                    "nodes": nodes,
                }
            }
        }

    def test_every_page_is_walked_to_the_end(self) -> None:
        pages = [
            self.page([{"handle": "a"}], "cursor-1"),
            self.page([{"handle": "b"}], None),
        ]
        seen: list[str | None] = []

        def fetch(url: str, body: bytes, headers: dict) -> bytes:
            seen.append(json.loads(body)["variables"]["cursor"])
            return json.dumps(pages[len(seen) - 1]).encode()

        nodes = list(Storefront(fetch).sweep())

        assert [node["handle"] for node in nodes] == ["a", "b"]
        assert seen == [None, "cursor-1"]

    def test_the_token_is_sent_as_a_storefront_header(self) -> None:
        sent: dict[str, str] = {}

        def fetch(url: str, body: bytes, headers: dict) -> bytes:
            sent.update(headers)
            return json.dumps(self.page([], None)).encode()

        list(Storefront(fetch).sweep())

        assert sent["X-Shopify-Storefront-Access-Token"]

    def test_a_rotated_token_is_reported_rather_than_retried(self) -> None:
        calls = []

        def fetch(url: str, body: bytes, headers: dict) -> bytes:
            calls.append(url)
            return json.dumps(
                {"errors": [{"message": "Access denied"}]}
            ).encode()

        with pytest.raises(RemoteFailure, match="Access denied"):
            list(Storefront(fetch).sweep())

        assert len(calls) == 1

    def test_an_unreachable_store_is_a_remote_failure(self) -> None:
        def fetch(url: str, body: bytes, headers: dict) -> bytes:
            raise OSError("connection refused")

        with pytest.raises(RemoteFailure, match="could not be reached"):
            list(Storefront(fetch).sweep())

    def test_a_response_that_is_not_json_is_a_remote_failure(self) -> None:
        def fetch(url: str, body: bytes, headers: dict) -> bytes:
            return b"<html>maintenance</html>"

        with pytest.raises(RemoteFailure, match="not JSON"):
            list(Storefront(fetch).sweep())


class TestWindows:
    """Umall lists more products than one connection may be paged through."""

    def node(self, handle: str, created: str) -> dict:
        return {"handle": handle, "createdAt": created}

    def sweep_over(self, pages: list[dict]) -> tuple[list[dict], list[dict]]:
        """Sweep a canned sequence of pages, recording what was asked for."""
        asked: list[dict] = []

        def fetch(url: str, body: bytes, headers: dict) -> bytes:
            asked.append(json.loads(body)["variables"])
            return json.dumps(pages[len(asked) - 1]).encode()

        return list(Storefront(fetch).sweep()), asked

    def page(
        self, nodes: list[dict], *, more: bool, cursor: str | None = None
    ) -> dict:
        return {
            "data": {
                "products": {
                    "pageInfo": {"hasNextPage": more, "endCursor": cursor},
                    "nodes": nodes,
                }
            }
        }

    def test_a_window_resumes_from_the_last_creation_time(self) -> None:
        """The second connection is filtered, not cursor-continued."""
        pages = [
            self.page([self.node("a", "2026-01-01T00:00:00Z")], more=False),
            self.page([self.node("b", "2026-02-01T00:00:00Z")], more=False),
            self.page([], more=False),
        ]

        nodes, asked = self.sweep_over(pages)

        assert [node["handle"] for node in nodes] == ["a", "b"]
        assert asked[0]["query"] is None
        assert asked[1]["query"] == 'created_at:>="2026-01-01T00:00:00Z"'

    def test_the_timestamp_is_quoted(self) -> None:
        """Unquoted, Shopify returns rows before the bound."""
        pages = [
            self.page([self.node("a", "2026-01-01T00:00:00Z")], more=False),
            self.page([], more=False),
        ]

        _, asked = self.sweep_over(pages)

        assert '"2026-01-01T00:00:00Z"' in asked[1]["query"]

    def test_a_product_on_the_boundary_is_not_yielded_twice(self) -> None:
        """Windows overlap by design: the shared second must not be dropped."""
        boundary = self.node("a", "2026-01-01T00:00:00Z")
        pages = [
            self.page([boundary], more=False),
            self.page(
                [boundary, self.node("b", "2026-01-01T00:00:00Z")],
                more=False,
            ),
            self.page([boundary], more=False),
        ]

        nodes, _ = self.sweep_over(pages)

        assert [node["handle"] for node in nodes] == ["a", "b"]

    def test_a_window_of_nothing_new_ends_the_sweep(self) -> None:
        """More than a cap's worth sharing one second cannot loop forever."""
        same = self.node("a", "2026-01-01T00:00:00Z")
        pages = [self.page([same], more=False), self.page([same], more=False)]

        nodes, asked = self.sweep_over(pages)

        assert [node["handle"] for node in nodes] == ["a"]
        assert len(asked) == 2
