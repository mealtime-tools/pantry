"""Open Food Facts: discovery over the public Search-a-licious index.

Credential-free, and a successful search is reused for 24 hours from a
disposable cache because the index asks callers to stay under ten searches a
minute. Acquiring a barcode goes through that same cached query rather than a
second endpoint, so the one rate limit stays in one place.
"""

from pantry.nutrition import nutrients_for_storage
from pantry.open_food_facts import OpenFoodFacts, RemoteFailure
from pantry.products import NUTRIENT_KEYS, Product
from pantry.providers import AcquireOptions, Provider, Reference
from pantry.sites import build_record

# The index does not match a barcode as free text — measured: `q=<barcode>`
# returns nothing — so an exact acquire asks for the field, which answers with
# the one row or none.
_CODE_QUERY = "code:{}"


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
        query = _CODE_QUERY.format(barcode)
        for hit in self._client.search(query, limit=1):
            if hit.get("id") == barcode:
                return hit

        raise RemoteFailure(
            f"Open Food Facts has no product {barcode}; "
            f"enter it with `pantry add --input -` instead"
        )
