"""What a catalogue row is, and what it costs per unit of nutrition."""

from decimal import Decimal

import pytest

from pantry.umall import (
    catalog_entry,
    is_external_gtin,
    is_food,
    net_grams,
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


class TestIsFood:
    """A general store lists nappies. A nutrition tool should not hold them."""

    @pytest.mark.parametrize(
        "category",
        ["Face Care", "Kitchenware & Accessories", "Laundry", "Pets"],
    )
    def test_a_thing_nobody_eats_is_not_food(self, category: str) -> None:
        assert not is_food(category)

    @pytest.mark.parametrize(
        "category",
        ["Tofu & Soy Products", "Instant Noodles", "Dried Groceries"],
    )
    def test_a_thing_people_eat_is(self, category: str) -> None:
        assert is_food(category)

    @pytest.mark.parametrize(
        "category", ["Alcoholic Drinks", "Health & Pharmacy", "Gift Pack"]
    )
    def test_anything_that_may_carry_calories_is_kept(
        self, category: str
    ) -> None:
        """Alcohol has energy, and a hamper may be full of food."""
        assert is_food(category)

    def test_an_unlisted_category_counts_as_food(self) -> None:
        """A category the store adds later is kept, not silently dropped."""
        assert is_food("Artisanal Space Rations")

    def test_a_missing_category_counts_as_food(self) -> None:
        assert is_food(None)
        assert is_food("")

    def test_the_name_is_matched_however_it_is_cased_or_spaced(self) -> None:
        assert not is_food("  face care  ")

    def test_a_keyword_alone_does_not_exclude(self) -> None:
        """"Care" appears in non-food names; it must not condemn a food one."""
        assert is_food("Careful Farms Rolled Oats")


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

    def test_the_title_beats_the_shipping_weight(self) -> None:
        """78 g of noodles in a 226 g parcel: the parcel is not the food."""
        entry = catalog_entry(
            node(
                title="Nissin Cup Noodles - 78g",
                variant={"weight": 226.0, "weightUnit": "GRAMS"},
            )
        )

        assert entry is not None
        assert entry["pack_grams"] == Decimal("78")

    def test_the_shipping_weight_is_used_where_no_title_states_one(
        self,
    ) -> None:
        entry = catalog_entry(
            node(
                title="Frozen Kurobuta Pork Hind Hock",
                variant={"weight": 1.25, "weightUnit": "KILOGRAMS"},
            )
        )

        assert entry is not None
        assert entry["pack_grams"] == Decimal("1250")

    @pytest.mark.parametrize("unit", ["POUNDS", "OUNCES"])
    def test_an_imperial_weight_is_left_absent(self, unit: str) -> None:
        """Converting would invent a precision the store never stated."""
        entry = catalog_entry(
            node(title="Mystery Item", variant={"weightUnit": unit})
        )

        assert entry is not None
        assert "pack_grams" not in entry

    def test_an_unweighed_product_omits_grams(self) -> None:
        """Fresh produce sold by the piece: zero is not a weight."""
        entry = catalog_entry(
            node(title="Papaya - 1 Piece", variant={"weight": 0.0})
        )

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


class TestNetGrams:
    """What the title says is in the pack, which is not what it ships at."""

    def test_a_plain_size(self) -> None:
        assert net_grams("Max Bean Silken Tofu 300g") == Decimal("300")

    def test_kilograms_and_litres_become_grams(self) -> None:
        assert net_grams("Frozen Dumplings 1.25kg") == Decimal("1250")
        assert net_grams("Soy Sauce 1.9L") == Decimal("1900")

    def test_millilitres_are_read_as_grams(self) -> None:
        """As a per-100 mL panel is: exact for water, close for sauces."""
        assert net_grams("Haitian Light Soy Sauce 500ml") == Decimal("500")

    def test_a_multipack_multiplies(self) -> None:
        assert net_grams("Wang Stir-Fried Ramen 122g x 4") == Decimal("488")

    def test_a_count_before_the_size_multiplies_too(self) -> None:
        assert net_grams("Yakult 3 x 200ml") == Decimal("600")

    def test_a_count_written_in_words_multiplies(self) -> None:
        """A case of water is not one bottle, whatever the title's grammar."""
        assert net_grams(
            "Evian Natural Mineral Water 500ml - 24 Bottles/Case"
        ) == Decimal("12000")

    def test_the_last_size_wins(self) -> None:
        """A title naming both the unit and the pack states the pack last."""
        assert net_grams("Mini Bowl 41g, 12 Pack, 492g") == Decimal("492")

    def test_a_word_that_is_not_a_pack_does_not_multiply(self) -> None:
        assert net_grams("Tofu 300g, Serves 4") == Decimal("300")

    def test_a_title_with_no_size_states_nothing(self) -> None:
        assert net_grams("Papaya - 1 Piece") is None

    def test_a_bare_number_is_not_a_size(self) -> None:
        assert net_grams("Pocky Strawberry 2026 Edition") is None


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
