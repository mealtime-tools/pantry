"""What a catalogue row is, and what it costs per unit of nutrition."""

from decimal import Decimal

import pytest

from pantry.umall import (
    catalog_entry,
    is_external_gtin,
    price_per_100_grams,
    price_per_100_kcal,
    price_per_gram,
)


def node(**overrides: object) -> dict:
    """One Storefront product node, in the shape the API returns it."""
    variant = {
        "sku": "A9352792000258",
        "barcode": "9352792000258",
        "weight": 300.0,
        "weightUnit": "GRAMS",
        "price": {"amount": "4.29", "currencyCode": "AUD"},
        "availableForSale": True,
    }
    variant.update(overrides.pop("variant", {}))  # type: ignore[arg-type]
    base = {
        "handle": "max-bean-silken-tofu-300g",
        "title": "Max Bean Silken Tofu 300g",
        "vendor": "Max Bean",
        "productType": "Tofu",
        "tags": ["tofu", "fresh"],
        "variants": {"nodes": [variant]},
    }
    base.update(overrides)
    return base


class TestExternalGtin:
    """Only a manufacturer's barcode can be looked up somewhere else."""

    @pytest.mark.parametrize(
        "barcode",
        ["9352792000258", "8850643003416", "6930812438378", "4006501235213"],
    )
    def test_a_manufacturer_barcode_is_external(self, barcode: str) -> None:
        assert is_external_gtin(barcode)

    @pytest.mark.parametrize(
        "barcode",
        [
            # The restricted ranges: a code the store issued to itself.
            "2026082009142",
            "9202402231777",
            # Not a barcode at all, or one whose check digit disagrees.
            "202608200914",
            "9352792000259",
            "",
            "abcdefghijklm",
        ],
    )
    def test_an_in_store_or_malformed_code_is_not(self, barcode: str) -> None:
        assert not is_external_gtin(barcode)

    def test_a_none_barcode_is_not_external(self) -> None:
        assert not is_external_gtin(None)


class TestCatalogEntry:
    """The row the catalogue holds, and what it refuses to hold."""

    def test_a_product_becomes_a_row(self) -> None:
        entry = catalog_entry(node())

        assert entry == {
            "id": "9352792000258",
            "name": "Max Bean Silken Tofu 300g",
            "brand": "Max Bean",
            "type": "Tofu",
            "tags": ["tofu", "fresh"],
            "price": Decimal("4.29"),
            "currency": "AUD",
            "pack_grams": Decimal("300"),
            "available": True,
            "url": "https://www.umall.com.au/products/"
            "max-bean-silken-tofu-300g",
            "ref": "off:9352792000258",
        }

    def test_an_in_store_code_carries_no_reference(self) -> None:
        """Nothing else knows the code, so no lookup is offered for it."""
        entry = catalog_entry(node(variant={"barcode": "9202402231777"}))

        assert entry is not None
        assert entry["id"] == "9202402231777"
        assert "ref" not in entry

    def test_a_kilogram_weight_becomes_grams(self) -> None:
        entry = catalog_entry(
            node(variant={"weight": 1.25, "weightUnit": "KILOGRAMS"})
        )

        assert entry is not None
        assert entry["pack_grams"] == Decimal("1250")

    @pytest.mark.parametrize("unit", ["POUNDS", "OUNCES"])
    def test_an_imperial_weight_is_left_absent(self, unit: str) -> None:
        """Converting would invent a precision the store never stated."""
        entry = catalog_entry(node(variant={"weightUnit": unit}))

        assert entry is not None
        assert "pack_grams" not in entry

    def test_an_unweighed_product_omits_grams(self) -> None:
        """Fresh produce sold by the piece: zero is not a weight."""
        entry = catalog_entry(node(variant={"weight": 0.0}))

        assert entry is not None
        assert "pack_grams" not in entry

    def test_a_product_with_no_variant_is_refused(self) -> None:
        assert catalog_entry(node(variants={"nodes": []})) is None

    def test_a_product_with_no_barcode_is_refused(self) -> None:
        """Identity is the barcode, so a row without one cannot be held."""
        assert catalog_entry(node(variant={"barcode": None})) is None

    def test_a_product_with_no_title_is_refused(self) -> None:
        assert catalog_entry(node(title="")) is None

    def test_an_unpriced_product_is_refused(self) -> None:
        assert catalog_entry(node(variant={"price": None})) is None

    def test_a_missing_brand_is_empty_rather_than_absent(self) -> None:
        entry = catalog_entry(node(vendor=""))

        assert entry is not None
        assert entry["brand"] == ""


class TestUnitPrice:
    """What a pack costs per unit of the thing being compared."""

    def test_price_per_100_grams(self) -> None:
        assert price_per_100_grams(
            Decimal("4.29"), Decimal("300")
        ) == Decimal("1.43")

    def test_price_per_100_kcal_uses_the_whole_pack(self) -> None:
        """300 g at 55 kcal per 100 g is 165 kcal, so $4.29 buys 165."""
        assert price_per_100_kcal(
            Decimal("4.29"), Decimal("300"), Decimal("55")
        ) == Decimal("2.6")

    def test_price_per_gram_of_protein(self) -> None:
        """300 g at 5 g per 100 g is 15 g of protein for $4.29."""
        assert price_per_gram(
            Decimal("4.29"), Decimal("300"), Decimal("5")
        ) == Decimal("0.286")

    @pytest.mark.parametrize("grams", [None, Decimal("0")])
    def test_no_weight_means_no_unit_price(
        self, grams: Decimal | None
    ) -> None:
        price = Decimal("4.29")

        assert price_per_100_grams(price, grams) is None
        assert price_per_100_kcal(price, grams, Decimal("55")) is None
        assert price_per_gram(price, grams, Decimal("5")) is None

    @pytest.mark.parametrize("figure", [None, Decimal("0")])
    def test_a_nutrient_none_of_it_has_no_price_per_unit(
        self, figure: Decimal | None
    ) -> None:
        """Dividing by it reports an infinite price, not an unknown one."""
        assert (
            price_per_100_kcal(Decimal("4.29"), Decimal("300"), figure) is None
        )
        assert price_per_gram(Decimal("4.29"), Decimal("300"), figure) is None

    def test_no_price_means_no_unit_price(self) -> None:
        assert price_per_100_grams(None, Decimal("300")) is None
