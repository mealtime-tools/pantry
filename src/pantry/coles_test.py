"""Reading a Coles search payload, and the url a row is addressed by."""

from decimal import Decimal

from pantry.coles import product_url, read_search

# Trimmed from a live `__NEXT_DATA__` payload on 2026-08-30, keeping only the
# keys read here. The first two rows are the shop's own first two.
PAYLOAD = {
    "searchResults": {
        "noOfResults": 5,
        "results": [
            {
                "_type": "PRODUCT",
                "id": 1145381,
                "name": "High Protein Cheese & Crackers",
                "brand": "Bega",
                "size": "36g",
                "availability": True,
                "pricing": {"now": 3.7},
            },
            {
                "_type": "PRODUCT",
                "id": 7699284,
                "name": "Cheese Tasty Protein Grated",
                "brand": "Bega",
                "size": "250g",
                "availability": True,
                "pricing": {"now": 8},
            },
            {"_type": "SINGLE_TILE", "id": 99, "name": "an advertisement"},
        ],
    }
}


def test_a_row_becomes_an_offer_with_its_shelf_price() -> None:
    first = read_search(PAYLOAD, limit=5)[0]

    assert first["id"] == "1145381"
    assert first["name"] == "High Protein Cheese & Crackers"
    assert first["brand"] == "Bega"
    assert first["price"] == Decimal("3.7")
    assert first["available"] is True


def test_the_pack_size_prices_the_food_not_the_pack() -> None:
    grated = read_search(PAYLOAD, limit=5)[1]

    assert grated["pack_grams"] == Decimal("250")
    assert grated["price_per_100g"] == Decimal("3.2")


def test_only_products_are_offers() -> None:
    """The shelf carries ad tiles and banners in the same list."""
    assert [r["id"] for r in read_search(PAYLOAD, limit=5)] == [
        "1145381",
        "7699284",
    ]


def test_a_result_carries_the_ref_that_fetches_its_panel() -> None:
    grated = read_search(PAYLOAD, limit=5)[1]

    assert grated["ref"] == (
        "coles:https://www.coles.com.au/product"
        "/bega-cheese-tasty-protein-grated-250g-7699284"
    )


def test_no_nutrition_is_invented_from_a_shelf_row() -> None:
    assert "kcal" not in read_search(PAYLOAD, limit=5)[0]


def test_the_limit_counts_offers() -> None:
    assert len(read_search(PAYLOAD, limit=1)) == 1


def test_a_payload_without_results_is_an_empty_shelf() -> None:
    assert read_search({}, limit=5) == []
    assert read_search({"searchResults": {}}, limit=5) == []
    assert read_search(None, limit=5) == []


def test_a_url_is_the_slug_coles_prints_plus_the_id() -> None:
    """Verified against the address bar: brand, name, size, then the id."""
    assert product_url("6647721", "Coles", "Full Cream Milk", "2L") == (
        "https://www.coles.com.au/product/coles-full-cream-milk-2l-6647721"
    )


def test_punctuation_in_a_name_does_not_reach_the_url() -> None:
    assert product_url(
        "1145381", "Bega", "High Protein Cheese & Crackers", "36g"
    ) == (
        "https://www.coles.com.au/product"
        "/bega-high-protein-cheese-crackers-36g-1145381"
    )
