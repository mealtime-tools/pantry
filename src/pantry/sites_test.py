"""What a retailer's product page says, read from the page itself.

The payloads here are trimmed from pages fetched on 2026-08-30, keeping the
fields a record is built from and the titles the basis is read off.
"""

import pytest

from pantry.products import MILLILITRE_NOTE, UNSTATED_UNIT_NOTE
from pantry.sites import ProductRef, SiteError, read_product

COLES = ProductRef(
    source="coles",
    id="8578",
    url="https://www.coles.com.au/product/cheer-tasty-cheese-slices-500g-8578",
)
WOOLWORTHS = ProductRef(
    source="woolworths",
    id="6026666",
    url="https://www.woolworths.com.au/shop/productdetails/6026666",
)


def coles_page(title: str, gtin: str | None = "9311482014722") -> dict:
    product = {
        "name": "Tasty Cheese Slices",
        "brand": "Cheer",
        "nutrition": {
            "breakdown": [
                {"title": "Per Serving", "nutrients": []},
                {
                    "title": title,
                    "nutrients": [
                        {"nutrient": "Energy", "value": "1430kJ"},
                        {"nutrient": "Protein", "value": "24.6g"},
                        {"nutrient": "Fat, total", "value": "27.3g"},
                        {"nutrient": "Carbohydrate", "value": "1.4g"},
                    ],
                },
            ]
        },
    }
    if gtin is not None:
        product["gtin"] = gtin
    return {"product": product}


def woolworths_page(barcode: str | None = "9310053108556") -> dict:
    product = {
        "Name": "Bega High Protein Cheese & Lavosh Crackers",
        "Brand": "Bega",
    }
    if barcode is not None:
        product["Barcode"] = barcode
    return {
        "pdDetails": {
            "Product": product,
            "NutritionalInformation": [
                {"Name": "Energy", "Values": {"per100g": "1330kJ"}},
                {"Name": "Protein", "Values": {"per100g": "28g"}},
                {"Name": "Fat, Total", "Values": {"per100g": "14g"}},
                {"Name": "Carbohydrate", "Values": {"per100g": "17g"}},
            ],
        }
    }


class TestBarcode:
    """Both retailers print a GTIN, which is what joins them to a panel."""

    def test_coles_records_the_gtin_the_page_states(self) -> None:
        record = read_product(COLES, coles_page("Per 100g/ml"))

        assert record["barcode"] == "9311482014722"

    def test_woolworths_records_the_barcode_the_page_states(self) -> None:
        record = read_product(WOOLWORTHS, woolworths_page())

        assert record["barcode"] == "9310053108556"

    def test_a_page_without_one_omits_it_rather_than_emptying_it(self) -> None:
        record = read_product(COLES, coles_page("Per 100g", gtin=None))

        assert "barcode" not in record


class TestBasis:
    """Which unit the figures are stated in, where the page says at all."""

    def test_a_column_headed_for_both_units_states_neither(self) -> None:
        """Coles now titles the column `Per 100g/ml`. Confirmed live."""
        record = read_product(COLES, coles_page("Per 100g/ml"))

        assert record["basis_note"] == UNSTATED_UNIT_NOTE

    def test_a_millilitre_column_says_so(self) -> None:
        record = read_product(COLES, coles_page("Per 100mL"))

        assert record["basis_note"] == MILLILITRE_NOTE

    def test_a_gram_column_needs_no_caveat(self) -> None:
        record = read_product(COLES, coles_page("Per 100g"))

        assert "basis_note" not in record


def test_a_page_carrying_no_product_is_refused() -> None:
    with pytest.raises(SiteError, match="no product"):
        read_product(COLES, {})


def test_a_woolworths_placeholder_is_not_stored_as_a_name() -> None:
    """The same defect on the product page, which is what gets stored."""
    payload = {
        "pdDetails": {
            "Product": {"Name": "Quorn Mince NULL", "Brand": "Quorn"},
            "NutritionalInformation": [],
        }
    }
    ref = ProductRef(source="woolworths", id="349163", url="https://x/349163")

    assert read_product(ref, payload)["name"] == "Quorn Mince"
