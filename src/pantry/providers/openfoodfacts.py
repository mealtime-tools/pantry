"""Open Food Facts: discovery over the public Search-a-licious index.

Credential-free, and a successful answer is reused for 24 hours from a
disposable cache because the index asks callers to stay under ten searches a
minute.

Discovery and acquisition ask different endpoints because they want different
things. Searching by name is what the index is for. Acquiring wants a panel,
and the index does not reliably carry one: `code:8852511011448` comes back
named and empty, and `code:9310053108556` does not come back at all, while the
product endpoint answers both in full. A record without figures is not worth
storing, so an acquire asks the endpoint that has them.
"""

from pantry.nutrition import nutrients_for_storage
from pantry.open_food_facts import OpenFoodFacts, RemoteFailure
from pantry.products import NUTRIENT_KEYS, Product
from pantry.providers import AcquireOptions, Provider, Reference
from pantry.sites import build_record


class OpenFoodFactsProvider(Provider):
    """Community product data: candidates to search, records to acquire."""

    name = "openfoodfacts"
    searchable = True
    acquirable = True

    def __init__(self, client: OpenFoodFacts) -> None:
        self._client = client

    def search(self, query: str, limit: int) -> list[dict]:
        return self._client.search(query, limit=limit)

    def acquire(self, ref: Reference, options: AcquireOptions) -> Product:
        """Turn one community row into a record, or refuse it.

        The panel goes through the same validation as a pasted label, and
        the row's pack size is not read.
        """
        hit = self._exact(ref.id)
        panel = nutrients_for_storage(
            {key: hit[key] for key in NUTRIENT_KEYS if key in hit}
        )
        return build_record(
            source=ref.source,
            product_id=ref.id,
            name=hit["name"],
            brand=hit.get("brand", ""),
            panel=panel,
            url=hit.get("url"),
        )

    def _exact(self, barcode: str) -> dict:
        """The row whose code is this barcode, and no near match instead."""
        hit = self._client.product(barcode)
        if hit is not None and hit.get("id") == barcode:
            return hit

        raise RemoteFailure(
            f"Open Food Facts has no product {barcode}; "
            f"enter it with `pantry add --input -` instead"
        )
