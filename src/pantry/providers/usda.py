"""FoodData Central: one food, by id, per 100 g.

A documented API with a key and a published rate limit, so no block rule or
page budget applies: nothing here refuses, and nothing needs pacing. The key
comes from `$USDA_API_KEY`, then `.env`, and never appears in output. Absent,
this provider is not enabled, and a clone with no key still builds and tests.
"""

from collections.abc import Mapping
from typing import Any

from pantry.credentials import find_key, resolve_key
from pantry.products import Product
from pantry.providers import AcquireOptions, Provider, Reference
from pantry.usda import fetch_food, to_product


class UsdaProvider(Provider):
    """Acquire one FoodData Central food by its fdcId. Never a search."""

    name = "usda"
    acquirable = True

    def __init__(
        self,
        *,
        opener: Any = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._opener = opener
        self._env = env

    @property
    def enabled(self) -> bool:
        return find_key(env=self._env) is not None

    def acquire(self, ref: Reference, options: AcquireOptions) -> Product:
        key = resolve_key(options.api_key, env=self._env)
        return to_product(fetch_food(ref.id, key, opener=self._opener))
