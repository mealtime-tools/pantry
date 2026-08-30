"""Open Food Facts by barcode, and the disposable cache in front of it.

One question is asked here — what product is this code — because that is the
one Open Food Facts answers better than anything else. Its name search was
removed once `--source` stopped offering it: it ranked `almonds` above
`Crunchoco Almond` badly enough to be worse than the local store, and code
nothing calls is code nobody checks.

Results are candidates, not records: community-maintained, no proof of current
retailer availability, and nothing here writes to the durable local store. The
cache sits under `XDG_CACHE_HOME`, where losing it costs one request.
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

# Exact lookup by barcode, and not the search index, which is lossy: measured
# against it, `code:8852511011448` returns the name with an empty `nutriments`,
# and `code:9310053108556` returns nothing at all, while this answers both with
# a full panel. A panel is the only reason to ask.
PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{}.json"
_USER_AGENT = "pantry/0.1 (https://github.com/owahltinez/pantry)"
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
    """A credential-free barcode lookup, with an on-disk TTL cache."""

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

    def _path(self, barcode: str) -> Path:
        """One stable, filesystem-safe file per barcode."""
        digest = hashlib.sha256(barcode.encode("utf-8")).hexdigest()
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

    def product(self, barcode: str) -> dict | None:
        """The record this barcode names, or None if the database lacks it.

        A fresh cached answer is reused; otherwise the endpoint is asked and
        the answer kept. Only a success is cached: a failure raises before it
        reaches here, so a refusal never becomes the answer for a day.
        """
        path = self._path(barcode)
        cached = self._cached(path)
        if cached is None:
            cached = self._product(barcode)
            # Whole seconds: the one serializer here writes figures, not
            # floats.
            write_atomic(
                path,
                dumps({"cached_at": int(self._now()), "results": cached}),
            )

        return cached[0] if cached else None

    def _product(self, barcode: str) -> list[dict]:
        """Ask the product endpoint for exactly this code."""
        code = urllib.parse.quote(barcode, safe="")
        body = self._get(PRODUCT_URL.format(code))
        try:
            payload = json.loads(body, parse_float=Decimal)
        except ValueError as cause:
            raise RemoteFailure(
                f"Open Food Facts returned an invalid answer for {barcode}"
            ) from cause

        if not isinstance(payload, dict) or payload.get("status") != 1:
            return []

        hit = _parse_hit(payload.get("product"))
        return [hit] if hit is not None else []
