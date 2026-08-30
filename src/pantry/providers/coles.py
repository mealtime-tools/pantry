"""Coles: a live shelf, read with one plain request.

The search page is server-rendered, so unlike Woolworths there is no browser
and no visible window here. The cost is that it spends one of the four or five
page loads Coles serves before an interstitial, which is why a query is one
request and never a walk through pages.

Nothing is caught here. A refusal, an exhausted budget and a page that is not
a search page each already carry their own reason and their own exit code, and
wrapping them would only bury which one happened.

The panel is not here either. A result carries a `coles:<url>` ref, and
`pantry add` on it reads the product page, which is where the NIP and the GTIN
are.
"""

import urllib.parse
from collections.abc import Callable

from pantry.coles import SEARCH_URL, SOURCE, read_search
from pantry.providers import Provider
from pantry.sites import next_data


class ColesProvider(Provider):
    """Search the shelf. The panel is a `pantry add` on the result's ref."""

    name = SOURCE
    searchable = True

    def __init__(self, load: Callable[[str], str]) -> None:
        self._load = load

    def search(self, query: str, limit: int) -> list[dict]:
        url = SEARCH_URL.format(urllib.parse.quote_plus(query))
        return read_search(next_data(self._load(url)), limit)
