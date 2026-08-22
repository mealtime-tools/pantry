"""Open Food Facts discovery, and the disposable cache in front of it.

Results are candidates, not records: they are community-maintained, they are
not proof of current retailer availability, and nothing here writes to the
durable localstore. The cache is therefore under `XDG_CACHE_HOME`,
where losing
it costs one request, and it exists because the public index asks callers to
stay under ten searches a minute.
"""

import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pantry.store import write_atomic

SEARCH_URL = "https://search.openfoodfacts.org/search"
_USER_AGENT = "pantry/0.1 (https://github.com/owahltinez/pantry)"
_MAX_RESULTS = 100
_TTL_SECONDS = 24 * 60 * 60

_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|ml|g|l)\b", re.IGNORECASE)


class RemoteFailure(Exception):
    """Open Food Facts could not answer. Never retried here."""


def cache_dir(
    env: Mapping[str, str] | None = None, home: Path | None = None
) -> Path:
    """Disposable search data, kept apart from durable user records."""
    environ = os.environ if env is None else env
    cache = environ.get("XDG_CACHE_HOME")
    base = Path(cache) if cache else (home or Path.home()) / ".cache"
    return base / "pantry" / "open-food-facts"


def _number(value: Any) -> float | None:
    """Keep only finite, non-negative nutrient values the source supplied.

    Six places because the unit is grams: a trace mineral figure is a few
    thousandths of a gram, and fewer places would quantise it down to a zero
    that reads as "none of it" rather than "hardly any".
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return round(parsed, 6)


def _nutrients(values: Any) -> dict[str, float]:
    """Convert an Open Food Facts nutrient map to per-100 g names."""
    source = values if isinstance(values, dict) else {}
    mapped = {
        "kcal": _number(source.get("energy-kcal_100g")),
        "protein": _number(source.get("proteins_100g")),
        "fat": _number(source.get("fat_100g")),
        "carbohydrates": _number(source.get("carbohydrates_100g")),
        "dietary_fiber": _number(source.get("fiber_100g")),
        "sugar": _number(source.get("sugars_100g")),
        # The index publishes grams per 100 g, which is what a record holds.
        "sodium": _number(source.get("sodium_100g")),
    }
    return {k: v for k, v in mapped.items() if v is not None}


def _amount(value: Any) -> dict[str, float | str]:
    """Read a simple amount such as "100 g" without guessing odd units."""
    if not isinstance(value, str):
        return {}

    match = _AMOUNT.search(value)
    if not match:
        return {}
    return {"size": float(match.group(1)), "unit": match.group(2).lower()}


def _brand(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(item for item in value if isinstance(item, str))
    return value.strip() if isinstance(value, str) else ""


def _parse_hit(value: Any) -> dict | None:
    """Adapt one sufficiently identified row to the search-result shape."""
    if not isinstance(value, dict):
        return None

    code = value.get("code")
    name = value.get("product_name")
    product_id = code.strip() if isinstance(code, str) else ""
    label = name.strip() if isinstance(name, str) else ""
    if not product_id or not label:
        return None

    brand = _brand(value.get("brands"))
    quantity = value.get("quantity")
    result: dict[str, str | Mapping[str, float | str]] = {
        "source": "openfoodfacts",
        "id": product_id,
        "name": label,
        "brand": brand,
        "title": f"{label} ({brand})" if brand else label,
    }
    if isinstance(quantity, str) and quantity.strip():
        result["quantity"] = quantity.strip()

    result["nutrients"] = _nutrients(value.get("nutriments"))
    result["serving"] = _amount(value.get("serving_size"))
    result["url"] = (
        "https://world.openfoodfacts.org/product/"
        f"{urllib.parse.quote(product_id, safe='')}"
    )
    return result


def _default_get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        raise RemoteFailure(
            f"Open Food Facts search failed with HTTP {error.code}"
        ) from error
    except OSError as error:
        raise RemoteFailure(f"Open Food Facts is unreachable: {error}") from (
            error
        )


class OpenFoodFacts:
    """A credential-free Search-a-licious query, with an on-disk TTL cache."""

    def __init__(
        self,
        directory: Path,
        get: Callable[[str], str] | None = None,
        now: Callable[[], float] | None = None,
        ttl_seconds: int = _TTL_SECONDS,
    ) -> None:
        self._directory = directory
        self._get = get or _default_get
        self._now = now or time.time
        self._ttl = ttl_seconds

    def _path(self, query: str, limit: int) -> Path:
        """One stable, filesystem-safe key per query and result limit."""
        payload = json.dumps({"query": query, "limit": limit}, sort_keys=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return self._directory / f"{digest}.json"

    def _cached(self, path: Path) -> list[dict] | None:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

        stamp = record.get("cached_at")
        results = record.get("results")
        fresh = isinstance(stamp, (int, float))
        if not fresh or not isinstance(results, list):
            return None
        return results if self._now() - stamp <= self._ttl else None

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search, reusing a fresh cached answer if there is one.

        Only a successful search is cached: a failure is not an answer, and
        caching one would hide the retry the user is entitled to make.
        """
        page_size = min(max(limit, 0), _MAX_RESULTS)
        if page_size == 0:
            return []

        path = self._path(query, page_size)
        cached = self._cached(path)
        if cached is not None:
            return cached

        results = self._request(query, page_size)
        write_atomic(
            path, json.dumps({"cached_at": self._now(), "results": results})
        )
        return results

    def _request(self, query: str, page_size: int) -> list[dict]:
        # `boost_phrase` is what makes a multi-word product name rank above the
        # individual words appearing anywhere; `langs=en` narrows the index
        # without constraining geography, which is never identity evidence.
        params = urllib.parse.urlencode(
            {
                "q": query,
                "page": "1",
                "page_size": str(page_size),
                "boost_phrase": "true",
                "langs": "en",
            }
        )
        body = self._get(f"{SEARCH_URL}?{params}")

        try:
            payload = json.loads(body)
        except ValueError as cause:
            raise RemoteFailure(
                "Open Food Facts search returned an invalid response"
            ) from cause

        hits = payload.get("hits") if isinstance(payload, dict) else None
        if not isinstance(hits, list):
            raise RemoteFailure(
                "Open Food Facts search returned an invalid response"
            )

        parsed = (_parse_hit(hit) for hit in hits)
        return [hit for hit in parsed if hit is not None]
