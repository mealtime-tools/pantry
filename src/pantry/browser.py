"""Two uses for a real browser, for the two things a plain request cannot do.

Reading a panel is not one of them: both supermarkets serve the whole
nutrition payload to a plain request, so `BrowserTransport` is a fallback the
user asks for with `--browser` and nothing reaches for on its own.

Searching Woolworths is the other, and there a browser is the only way. The
results page carries no products and the request behind it is refused for
anything that is not one. That session is visible, because headless is
refused too.

Playwright is imported lazily so a clone without it still fetches.
"""

import urllib.parse
from collections.abc import Callable
from typing import Any

from pantry.woolworths import SEARCH_API, SEARCH_URL

# A navigation that produced no response at all; classified as a refusal.
_NO_RESPONSE_STATUS = 503

# How long to wait for the page to make its own search request, and how often
# to look. Measured 2.0-6.2s a query, so this is roughly double the worst.
_SEARCH_TIMEOUT_MS = 15000
_POLL_MS = 100


class BrowserTransport:
    """Loads pages through an open browser page. Injected, never constructed
    here, so a test can supply an object with the same two methods."""

    name = "chrome"

    def __init__(self, page: Any) -> None:
        self._page = page

    def load(self, url: str) -> tuple[int, str]:
        response = self._page.goto(url, wait_until="domcontentloaded")
        status = response.status if response else _NO_RESPONSE_STATUS
        return (status, self._page.content())


# The only install guidance pantry prints, so it has to be the command that
# works. `uv pip install` does not reach the environment `uv tool install`
# builds, and the distribution is `mealtime-pantry`, not `pantry`.
BROWSER_HINT = "uv tool install 'mealtime-pantry[browser]'"


def launch_chrome(headless: bool = True) -> tuple[Any, Any]:
    """Start a browser, preferring the Chrome already on the machine.

    The installed channel is tried first because a real Chrome is kept current
    by the user and costs no download. Neither is a disguise: this is the
    ordinary browser, driven ordinarily.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as cause:
        raise RuntimeError(
            f"driving a browser needs playwright: {BROWSER_HINT}"
        ) from cause

    driver = sync_playwright().start()
    try:
        browser = driver.chromium.launch(channel="chrome", headless=headless)
    except Exception:  # noqa: BLE001 - playwright raises its own error type
        # Expected where no Chrome is installed; only a second failure counts.
        browser = driver.chromium.launch(headless=headless)

    return (driver, browser)


class ChromeSearch:
    """A Woolworths search, read from the request the page makes itself.

    The window is visible because headless is refused: measured, it is served
    "Access Denied" where a headed Chrome is served the shop. Navigation waits
    only for the document, since the page holds connections open and never
    goes idle, and the results are taken from the response as it arrives.
    """

    def __init__(self, page: Any, close: Callable[[], None]) -> None:
        self._page = page
        self._close = close
        self._captured: list[Any] = []
        page.on("response", self._capture)

    def _capture(self, response: Any) -> None:
        if SEARCH_API not in response.url or response.status != 200:
            return
        try:
            self._captured.append(response.json())
        except Exception:  # noqa: BLE001 - a body that is not json is not one
            return

    def results(self, query: str) -> Any:
        """Load the ordinary search url and hand back what it asked for."""
        self._captured.clear()
        term = urllib.parse.quote(query)
        self._page.goto(
            SEARCH_URL.format(term),
            wait_until="domcontentloaded",
            timeout=_SEARCH_TIMEOUT_MS,
        )

        for _ in range(_SEARCH_TIMEOUT_MS // _POLL_MS):
            if self._captured:
                return self._captured[0]
            self._page.wait_for_timeout(_POLL_MS)

        # No payload is an empty shelf as far as a caller is concerned; a
        # refusal would have arrived as a non-200 and been ignored above.
        return {}

    def close(self) -> None:
        self._close()


def open_search() -> ChromeSearch:
    """Start a visible Chrome and point it at the shop."""
    driver, browser = launch_chrome(headless=False)
    page = browser.new_page()

    def close() -> None:
        browser.close()
        driver.stop()

    return ChromeSearch(page, close)
