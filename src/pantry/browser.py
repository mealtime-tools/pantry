"""The browser fallback, for the day a site stops server-rendering its panel.

Not the normal path: both supermarkets return the whole nutrition payload to a
plain request, which leaves more of the page budget for actual products. The
user asks for this explicitly with `--browser`, and Playwright is imported
lazily so a clone without it still fetches.
"""

from typing import Any

# A navigation that produced no response at all; classified as a refusal.
_NO_RESPONSE_STATUS = 503


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


def launch_chrome() -> tuple[Any, Any]:
    """Start a browser, preferring the Chrome already on the machine.

    The installed channel is tried first because a real Chrome is kept current
    by the user and costs no download. Neither is a disguise: this is the
    ordinary browser, driven ordinarily.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as cause:
        raise RuntimeError(
            "the browser fallback needs playwright: "
            "uv pip install 'pantry[browser]'"
        ) from cause

    driver = sync_playwright().start()
    try:
        browser = driver.chromium.launch(channel="chrome")
    except Exception:  # noqa: BLE001 - playwright raises its own error type
        # Expected where no Chrome is installed; only a second failure counts.
        browser = driver.chromium.launch()

    return (driver, browser)
