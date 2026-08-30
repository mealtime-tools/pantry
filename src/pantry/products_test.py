"""What a stored figure is, and what restating one may do to it."""

from decimal import Decimal

import pytest

from pantry.data import data_dir, read_shards
from pantry.jsonfmt import dumps
from pantry.products import (
    NUTRIENT_KEYS,
    ProductError,
    assert_product_record,
    parse_jsonl,
    record_keys,
    restate,
)

_LINE = '{"id":"1","name":"Food","brand":"","kcal":391,"fat":0.28,"grams":100}'


def test_a_figure_is_read_as_the_decimal_its_line_states() -> None:
    """A float reads 0.28 back as 0.2799999999999999822364316059974953532."""
    (product,) = parse_jsonl(_LINE, source="coles")

    assert product["fat"] == Decimal("0.28")
    assert isinstance(product["fat"], Decimal)
    # A whole number stays whole, so it is written back without a `.0`.
    assert product["kcal"] == 391
    assert isinstance(product["kcal"], int)


def test_no_shipped_figure_is_a_float() -> None:
    """The type is the guarantee; rounding it back afterwards is not one."""
    for product in read_shards(data_dir()):
        for key in ("grams", *NUTRIENT_KEYS):
            assert not isinstance(product.get(key), float), (product, key)


def test_restating_a_fat_figure_lands_on_the_decimal_a_label_printed() -> None:
    """0.7 g of fat per 100 g, over 40 g, is 0.28 g.

    The same arithmetic in binary floats is 0.27999999999999997, which a
    record and then a recipe file carried verbatim. Nothing rounds it back
    here: the arithmetic never leaves the decimals the label was printed in.
    """
    assert 0.7 * (40 / 100) == 0.27999999999999997

    exact = Decimal("0.7") * 40 / 100
    restated = restate({"fat": Decimal("0.7")}, 100, 40)

    assert exact == Decimal("0.28")
    assert restated["fat"] == Decimal("0.28")
    assert dumps(restated) == '{"fat":0.28}'


@pytest.mark.parametrize(
    ("stated", "grams", "written"),
    [
        ("0.7", 40, "0.28"),
        ("0.1", 280, "0.28"),
        ("8.1", 70, "5.67"),
        ("0.07", 2900, "2.03"),
    ],
)
def test_a_restated_figure_is_written_in_the_digits_it_has(
    stated: str, grams: int, written: str
) -> None:
    """Each of these is a product two floats cannot state between them."""
    figure = Decimal(stated)

    assert dumps(restate({"fat": figure}, 100, grams)["fat"]) == written


def test_restating_divides_last_so_a_whole_figure_stays_whole() -> None:
    """1173 kcal for 300 g is 391 for 100 g, not 390.999999."""
    restated = restate({"kcal": 1173, "carbs": Decimal("166.5")}, 300)

    assert restated["kcal"] == 391
    assert restated["carbs"] == Decimal("55.5")


class TestBarcode:
    """The GTIN a retailer prints, which is what joins it to another source."""

    def test_a_barcode_is_a_key_a_record_may_carry(self) -> None:
        record = {
            "source": "woolworths",
            "id": "6026666",
            "name": "Bega High Protein Cheese",
            "brand": "Bega",
            "barcode": "9310053108556",
            "grams": 100,
            "kcal": Decimal("318"),
        }

        assert_product_record(record)

    def test_a_barcode_is_written_beside_the_identity(self) -> None:
        assert "barcode" in record_keys({})

    def test_a_barcode_is_refused_rather_than_coerced(self) -> None:
        """Read as a number it has already lost its leading zeros."""
        record = {
            "source": "woolworths",
            "id": "6026666",
            "name": "Bega High Protein Cheese",
            "brand": "Bega",
            "barcode": 9310053108556,
            "grams": 100,
            "kcal": Decimal("318"),
        }

        with pytest.raises(ProductError, match="barcode"):
            assert_product_record(record)
