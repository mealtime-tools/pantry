"""Open Food Facts: a barcode resolved to a panel, and nothing else.

Credential-free, and a successful answer is reused for 24 hours from a
disposable cache.

Not a search source. Its name search was poor enough to be worse than the
local store — `almonds` returned `Crunchoco Almond` — so it left `--source`
and this provider answers only `add off:<barcode>`. That is the one thing it
does better than anything else here: a retailer says what exists and what it
costs, and this supplies the figures the retailer withheld.
"""

from pantry.nutrition import nutrients_for_storage
from pantry.open_food_facts import OpenFoodFacts, RemoteFailure
from pantry.products import NUTRIENT_KEYS, Product
from pantry.providers import AcquireOptions, Provider, Reference
from pantry.sites import build_record


class OpenFoodFactsProvider(Provider):
    """Community product data, reached by barcode only."""

    name = "openfoodfacts"
    acquirable = True

    def __init__(self, client: OpenFoodFacts) -> None:
        self._client = client

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
            # The id here is the GTIN, but only this key says so to a reader
            # joining these records to a retailer's row.
            barcode=ref.id,
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
