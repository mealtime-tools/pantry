"""Provider selection and the public reference forms."""

import pytest
from agentcli import UsageError

from pantry.providers import (
    SHOP_NAMES,
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


def test_only_umall_is_currently_a_live_search_shop() -> None:
    assert SHOP_NAMES == ("umall",)


def test_the_store_is_the_silent_default() -> None:
    providers = Providers([Searcher("local"), Searcher("umall")])

    assert names(providers.searchers()) == ["local"]


def test_a_shop_replaces_the_store_for_that_search() -> None:
    providers = Providers([Searcher("local"), Searcher("umall")])

    assert names(providers.searchers(shop="umall")) == ["umall"]


def test_an_unavailable_shop_yields_no_searcher() -> None:
    providers = Providers([Searcher("local")])

    assert providers.searchers(shop="umall") == []


def test_a_woolworths_stockcode_resolves_to_its_provider() -> None:
    assert resolve_reference("woolworths:6026666") == Reference(
        provider="woolworths",
        source="woolworths",
        id="6026666",
    )


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
