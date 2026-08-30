"""What `add barcode:<barcode>` stores, and what it refuses to store."""

from decimal import Decimal

import pytest

from pantry.open_food_facts import RemoteFailure
from pantry.providers import AcquireOptions, Reference
from pantry.providers.openfoodfacts import OpenFoodFactsProvider

# One row in the shape the client hands back, trimmed to what is read.
MAYONNAISE = {
    "source": "openfoodfacts",
    "id": "8852511011448",
    "name": "MAYONNAISE",
    "brand": "Kewpie",
    "url": "https://world.openfoodfacts.org/product/8852511011448",
    "kcal": Decimal("724.98"),
    "fat": Decimal("80"),
}


class Client:
    """Stands in for the http client; answers one barcode and no other."""

    def __init__(self, hit: dict | None) -> None:
        self._hit = hit

    def product(self, barcode: str) -> dict | None:
        return self._hit


def acquire(hit: dict | None, barcode: str = "8852511011448"):
    provider = OpenFoodFactsProvider(Client(hit))
    ref = Reference("openfoodfacts", "openfoodfacts", barcode)
    return provider.acquire(ref, AcquireOptions())


def test_the_community_database_is_reached_by_barcode_only() -> None:
    """Its name search ranked worse than the store, so it left `--source`."""
    assert not OpenFoodFactsProvider.searchable
    assert OpenFoodFactsProvider.acquirable


def test_a_barcode_becomes_a_record_with_its_panel() -> None:
    record = acquire(MAYONNAISE)

    assert record["id"] == "8852511011448"
    assert record["name"] == "MAYONNAISE"
    # Energy is stored the way a panel prints it, so 724.98 rounds.
    assert record["kcal"] == Decimal("725")


def test_the_barcode_is_stored_as_the_join_key_it_is() -> None:
    """The id is the GTIN here, but only `barcode` says so to a reader."""
    assert acquire(MAYONNAISE)["barcode"] == "8852511011448"


def test_a_code_the_database_lacks_is_refused_not_invented() -> None:
    with pytest.raises(RemoteFailure):
        acquire(None)


def test_a_row_answering_a_different_code_is_refused() -> None:
    """A near match is not the product asked for, whatever it is named."""
    with pytest.raises(RemoteFailure):
        acquire(MAYONNAISE, barcode="9310053108556")
