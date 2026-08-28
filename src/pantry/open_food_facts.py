"""Open Food Facts discovery, and the disposable cache in front of it.

Results are candidates, not records: community-maintained, no proof of current
retailer availability, and nothing here writes to the durable localstore. The
cache sits under `XDG_CACHE_HOME`, where losing it costs one request, and
exists because the public index asks for under ten searches a minute.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pantry.jsonfmt import dumps
from pantry.store import write_atomic

SEARCH_URL = "https://search.openfoodfacts.org/search"
_USER_AGENT = "pantry/0.1 (https://github.com/owahltinez/pantry)"
_MAX_RESULTS = 100
_TTL_SECONDS = 24 * 60 * 60


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


def _number(value: Any) -> Decimal | None:
    """Keep only finite, non-negative nutrient values the source supplied.

    Six places because the unit is grams: a trace mineral figure is a few
    thousandths of a gram, and fewer places would quantise it down to a zero
    that reads as "none of it" rather than "hardly any". It is a cap on what
    the community index states, not a repair: both the payload and the cache
    are parsed to Decimal, so no float reaches here to be repaired.
    """
    if isinstance(value, bool) or not isinstance(value, (int, Decimal, str)):
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return round(parsed, 6)


def _nutrients(values: Any) -> dict[str, Decimal]:
    """Convert an Open Food Facts nutrient map to per-100 g names."""
    source = values if isinstance(values, dict) else {}
    mapped = {
        "kcal": _number(source.get("energy-kcal_100g")),
        "protein": _number(source.get("proteins_100g")),
        "fat": _number(source.get("fat_100g")),
        "carbs": _number(source.get("carbohydrates_100g")),
        "fiber": _number(source.get("fiber_100g")),
        "sugar": _number(source.get("sugars_100g")),
        # The index publishes grams per 100 g, which is what a record holds.
        "sodium": _number(source.get("sodium_100g")),
    }
    return {k: v for k, v in mapped.items() if v is not None}


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
    result: dict[str, Any] = {
        "source": "openfoodfacts",
        "id": product_id,
        "name": label,
        "brand": brand,
        "title": f"{label} ({brand})" if brand else label,
    }
    result.update(_nutrients(value.get("nutriments")))
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
            record = json.loads(
                path.read_text(encoding="utf-8"), parse_float=Decimal
            )
        except (OSError, ValueError):
            return None

        stamp = record.get("cached_at")
        results = record.get("results")
        fresh = isinstance(stamp, int) and not isinstance(stamp, bool)
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
        # Whole seconds: the one serializer here writes figures, not floats.
        write_atomic(
            path,
            dumps({"cached_at": int(self._now()), "results": results}),
        )
        return results

    def _request(self, query: str, page_size: int) -> list[dict]:
        # `boost_phrase` ranks a whole name first; `langs` is not geography.
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
            payload = json.loads(body, parse_float=Decimal)
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
