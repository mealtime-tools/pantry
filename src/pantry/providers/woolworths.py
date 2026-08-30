"""Woolworths reference ownership before the Phase 2 reader lands."""

from pantry.open_food_facts import RemoteFailure
from pantry.products import Product
from pantry.providers import AcquireOptions, Provider, Reference


class WoolworthsProvider(Provider):
    """Claim stockcodes now; acquire them once the provider is implemented."""

    name = "woolworths"
    acquirable = True

    def acquire(self, ref: Reference, options: AcquireOptions) -> Product:
        raise RemoteFailure("Woolworths acquisition is not implemented")
