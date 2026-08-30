"""Provider selection and the public reference forms."""

import pytest
from agentcli import UsageError

from pantry.providers import (
    SEARCH_SOURCES,
    Provider,
    Providers,
    Reference,
    resolve_reference,
)


class Searcher(Provider):
    searchable = True

    def __init__(self, name: str) -> None:
        self.name = name


def names(providers: list[Provider]) -> list[str]:
    return [provider.name for provider in providers]


def test_only_umall_is_currently_a_live_search_source() -> None:
    assert SEARCH_SOURCES == ("umall",)


def test_the_store_is_the_silent_default() -> None:
    providers = Providers([Searcher("local"), Searcher("umall")])

    assert names(providers.searchers()) == ["local"]


def test_a_source_replaces_the_store_for_that_search() -> None:
    providers = Providers([Searcher("local"), Searcher("umall")])

    assert names(providers.searchers(source="umall")) == ["umall"]


def test_an_unavailable_source_yields_no_searcher() -> None:
    providers = Providers([Searcher("local")])

    assert providers.searchers(source="umall") == []


def test_a_woolworths_stockcode_resolves_to_its_product_page() -> None:
    """The stockcode is the whole address; the reader is the retailer's."""
    assert resolve_reference("woolworths:6026666") == Reference(
        provider="retailer",
        source="woolworths",
        id="6026666",
        url="https://www.woolworths.com.au/shop/productdetails/6026666",
    )


def test_a_woolworths_url_and_its_stockcode_name_the_same_thing() -> None:
    page = "https://www.woolworths.com.au/shop/productdetails/6026666"

    assert resolve_reference(page) == resolve_reference("woolworths:6026666")


def test_a_woolworths_stockcode_is_digits_only() -> None:
    with pytest.raises(UsageError, match="digits only"):
        resolve_reference("woolworths:bread")


def test_a_prefixed_coles_url_resolves_to_the_retailer_provider() -> None:
    url = "https://www.coles.com.au/product/oat-puffs-300g-1516814"

    assert resolve_reference(f"coles:{url}") == Reference(
        provider="retailer",
        source="coles",
        id="1516814",
        url=url,
    )
