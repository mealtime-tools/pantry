"""Coles and Woolworths product pages, and the cost of reading one.

Three rules, this provider's and not the CLI's, since no other source has a
page to be refused by: a block ends the session — no retry, no second user
agent, no proxy — because four or five loads is all the user gets before a
captcha, and the answer then is `pantry add --input -`; the page budget is
claimed before a request and counted even when refused; requests are paced.
"""

from collections.abc import Callable

from pantry.products import Product
from pantry.providers import AcquireOptions, Provider, Reference
from pantry.providers.pages import PageBudget, PageLoader, TransportSet
from pantry.sites import ProductRef, parse_product_page

# Low on purpose: the sites tolerate roughly four or five loads in a sitting.
DEFAULT_PAGE_BUDGET = 4

# Long enough to look like reading a page rather than walking a catalogue.
DEFAULT_PACE_MS = 3000


class RetailerProvider(Provider):
    """Read one supermarket product page and nothing else in the catalogue."""

    name = "retailer"
    acquirable = True

    def __init__(
        self,
        open_transports: Callable[[bool], TransportSet],
        *,
        pace_ms: int = DEFAULT_PACE_MS,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._open_transports = open_transports
        self._pace_ms = pace_ms
        self._sleep = sleep
        self._opened: TransportSet | None = None
        self._pages: PageLoader | None = None

    def acquire(self, ref: Reference, options: AcquireOptions) -> Product:
        """Load the page and read its panel.

        A transport is opened only once the caller is certain it needs one: the
        store check happens upstream, so nothing is opened for a product
        already held.
        """
        budget = (
            DEFAULT_PAGE_BUDGET if options.budget is None else options.budget
        )
        self._opened = self._open_transports(options.browser)
        self._pages = PageLoader(
            self._opened.transports,
            PageBudget(budget),
            self._pace_ms,
            self._sleep,
        )

        html = self._pages.load(ref.url or "")
        site = ProductRef(source=ref.source, id=ref.id, url=ref.url or "")
        return parse_product_page(site, html)

    def report(self) -> list[str]:
        """The budget is what the user is actually spending, so it is said."""
        if self._pages is None:
            return []

        spent = self._pages.spent
        limit = self._pages.budget.limit
        return [f"used {spent} of {limit} page loads this run"]

    def close(self) -> None:
        if self._opened is not None:
            self._opened.close()
            self._opened = None
