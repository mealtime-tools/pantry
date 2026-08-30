"""Reading the payload the search page's own request returns.

Trimmed from a live capture on 2026-08-30, keeping the fields a result is
built from. The nesting is the site's: a group per match, variants within it.
"""

from decimal import Decimal

from pantry.woolworths import read_search

BEGA = {
    "Stockcode": 6026666,
    "Barcode": "9310053108556",
    "Name": "Bega High Protein Cheese & Lavosh Crackers",
    "Brand": "Bega",
    "Price": 3.7,
    "PackageSize": "36g",
    "IsAvailable": True,
    "UrlFriendlyName": "bega-high-protein-cheese-lavosh-crackers",
}
SPREAD = {
    "Stockcode": 6069495,
    "Barcode": "9300650454385",
    "Name": "Philadelphia Protein Spread",
    "Brand": "Philadelphia",
    "Price": 4.5,
    "PackageSize": "215g",
    "IsAvailable": True,
}
FETTA = {
    "Stockcode": 6027911,
    "Barcode": "9322666000066",
    "Name": "Riverina Dairy Co High Protein Fetta",
    "Brand": "Riverina Dairy Co",
    "Price": 5.3,
    "PackageSize": "180g",
    "IsAvailable": True,
}


def payload(*products: dict) -> dict:
    return {"Products": [{"Products": [p]} for p in products]}


def test_a_group_yields_the_product_it_holds() -> None:
    found = read_search(payload(BEGA), limit=10)

    assert len(found) == 1
    assert found[0]["id"] == "6026666"
    assert found[0]["name"] == "Bega High Protein Cheese & Lavosh Crackers"


def test_a_result_carries_what_the_shelf_costs() -> None:
    found = read_search(payload(BEGA), limit=10)

    assert found[0]["price"] == Decimal("3.7")
    assert found[0]["pack_grams"] == Decimal("36")
    assert found[0]["currency"] == "AUD"


def test_a_result_names_the_reference_that_acquires_its_panel() -> None:
    """The stockcode is a whole address, so the panel is one add away."""
    found = read_search(payload(BEGA), limit=10)

    assert found[0]["ref"] == "woolworths:6026666"


def test_a_result_carries_the_barcode_for_joining() -> None:
    found = read_search(payload(BEGA), limit=10)

    assert found[0]["barcode"] == "9310053108556"


def test_a_stockcode_is_read_as_digits_not_as_a_number() -> None:
    """It arrives as an integer and is an identity, not a quantity."""
    found = read_search(payload(BEGA), limit=10)

    assert isinstance(found[0]["id"], str)


def test_a_row_with_no_stockcode_is_dropped_rather_than_guessed() -> None:
    found = read_search(payload({**BEGA, "Stockcode": None}), limit=10)

    assert found == []


def test_a_row_with_no_price_is_not_an_offer() -> None:
    found = read_search(payload({**BEGA, "Price": None}), limit=10)

    assert found == []


def test_the_limit_counts_products_not_groups() -> None:
    found = read_search(payload(BEGA, FETTA), limit=1)

    assert len(found) == 1


def test_a_payload_with_no_products_is_empty_not_an_error() -> None:
    assert read_search({}, limit=10) == []


def test_the_asked_for_product_outranks_the_shop_relevance_order() -> None:
    """The shop leads with a spread for "bega cheese"; the query did not."""
    found = read_search(payload(SPREAD, BEGA), limit=10, query="bega cheese")

    assert found[0]["id"] == "6026666"


def test_results_carry_how_well_they_answered() -> None:
    found = read_search(payload(BEGA), limit=10, query="bega cheese")

    assert found[0]["match"]["score"] > 0


def test_without_a_query_the_shop_order_is_kept() -> None:
    found = read_search(payload(SPREAD, BEGA), limit=10)

    assert [row["id"] for row in found] == ["6069495", "6026666"]
