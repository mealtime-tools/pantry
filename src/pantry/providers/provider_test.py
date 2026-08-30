"""Selection of the one search provider a command asks."""

from pantry.providers import SHOP_NAMES, Provider, Providers


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
