"""Spending page loads on a supermarket, carefully.

Three rules: a block ends the session, with no retry and nothing that makes the
client look less like what it is; the budget is hard, and counted even for a
refused request, because the site served it either way; requests are paced. The
transport is injected, so every test here runs offline, and only the retailer
provider uses any of this.
"""

import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

# A Chrome string, and the one place this client does not announce itself.
# Measured 2026-08-30 on the first request of a session, so no reputation had
# accumulated either way: with urllib's default agent, Woolworths never
# answers at all and the read times out, and Coles serves a 1 kB Incapsula
# interstitial as a 200. With this string both serve the product page. It is a
# filter on the header, not a judgement about the caller. Nothing further is
# disguised — pacing, the budget, and "a block ends the session" all stand.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

# Narrow on purpose: a working Coles page carries Incapsula and reCAPTCHA.
_BLOCK_MARKERS = (
    r"incapsula incident id",
    r"request unsuccessful",
    r"pardon our interruption",
    r"verify you are (?:a )?human",
    r"attention required!",
    r"access denied",
    r"unusual traffic",
    r"px-captcha",
)

# Statuses a site uses to say "not now": forbidden, rate limited, shed load.
_BLOCK_STATUSES = frozenset({401, 403, 429, 503})


class BudgetExhausted(Exception):
    """Raised instead of quietly making one more request."""

    def __init__(self, limit: int) -> None:
        super().__init__(
            f"page budget of {limit} is spent; nothing further was requested"
        )


class Blocked(Exception):
    """Raised when a site refuses. Never caught and retried anywhere."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"the site declined to serve this page ({reason}); "
            f"enter it with `pantry add --input -` instead"
        )


class HttpResponse(Protocol):
    """The part of a served response this file reads."""

    status: int

    def read(self) -> bytes:
        """Return the body bytes."""


class Opener(Protocol):
    """`urllib.request.urlopen`, or a test double standing in for it."""

    def __call__(
        self, request: urllib.request.Request, timeout: float
    ) -> AbstractContextManager[HttpResponse]:
        """Open one request and hand back its response."""


class Transport(Protocol):
    """One way of getting a page: a plain request, or a real browser."""

    name: str

    def load(self, url: str) -> tuple[int, str]:
        """Return the status and body of one page load."""


@dataclass
class TransportSet:
    """The transports for one run, and whatever must be shut down after."""

    transports: list[Transport]
    close: Callable[[], None] = lambda: None


class PageBudget:
    """A page load allowance for one run of the CLI."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.spent = 0

    @property
    def remaining(self) -> int:
        return self.limit - self.spent

    def claim(self) -> None:
        """Claim one load, or refuse before anything reaches the network."""
        if self.spent >= self.limit:
            raise BudgetExhausted(self.limit)
        self.spent += 1


def detect_block(status: int, body: str) -> str | None:
    """Say why a response is a refusal, or nothing if it is an answer.

    A 404 is deliberately not a block: it means the product is gone, which the
    caller reports differently and which does not end the session.
    """
    if status in _BLOCK_STATUSES:
        return f"HTTP {status}"

    for marker in _BLOCK_MARKERS:
        if re.search(marker, body, re.IGNORECASE):
            return f"matched /{marker}/"

    return None


class PlainTransport:
    """One plain request, ordinary user agent, and no cleverness."""

    name = "plain request"

    def __init__(self, opener: Opener | None = None) -> None:
        self._opener = opener or urllib.request.urlopen

    def load(self, url: str) -> tuple[int, str]:
        request = urllib.request.Request(
            url,
            headers={
                "user-agent": _USER_AGENT,
                "accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,*/*;q=0.8"
                ),
                "accept-language": "en-AU,en;q=0.9",
            },
        )

        # An error status is still a served page; its body says which it is.
        try:
            with self._opener(request, timeout=30) as response:
                body = response.read().decode("utf-8", "replace")
                return (response.status, body)
        except urllib.error.HTTPError as error:
            return (error.code, error.read().decode("utf-8", "replace"))


def _refusal_reason(error: BaseException) -> str:
    """Network failures that mean the far end refused, not that it is down.

    Woolworths' `/apis/ui/` JSON endpoints answer a plain client with an
    HTTP/2 stream reset rather than a status code. Treating that as a
    transient outage would put this straight into the retry loop the whole
    file exists to avoid.
    """
    reason = getattr(error, "reason", None)
    return str(reason) if reason else str(error) or type(error).__name__


class PageLoader:
    """Load pages under a budget, stopping for good when a site says no."""

    def __init__(
        self,
        transports: list[Transport],
        budget: PageBudget,
        pace_ms: int,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._transports = transports
        self.budget = budget
        self._pace_ms = pace_ms
        self._sleep = sleep or time.sleep
        self._requested = False
        self._blocked: str | None = None

    @property
    def spent(self) -> int:
        return self.budget.spent

    def _attempt(self, transport: Transport, url: str) -> tuple[str, str]:
        """Return ("body", text) or ("blocked", reason); never raise."""
        try:
            status, body = transport.load(url)
        except Exception as error:  # noqa: BLE001 - any failure is a refusal
            return ("blocked", f"{transport.name}: {_refusal_reason(error)}")

        reason = detect_block(status, body)
        if reason:
            return ("blocked", f"{transport.name}: {reason}")
        return ("body", body)

    def load(self, url: str) -> str:
        """Fetch one page, or explain which rule stopped it.

        Falling through to a second transport is a fallback, not a retry: each
        is tried once, and the CLI only supplies a browser when asked.
        """
        # Once a site has refused, nothing else is requested in this run.
        if self._blocked:
            raise Blocked(self._blocked)

        reason = "no transport was configured"
        for transport in self._transports:
            self.budget.claim()

            # No wait before the run's first request, one before every other.
            if self._requested and self._pace_ms:
                self._sleep(self._pace_ms / 1000)
            self._requested = True

            kind, value = self._attempt(transport, url)
            if kind == "body":
                return value
            reason = value

        self._blocked = reason
        raise Blocked(reason)
