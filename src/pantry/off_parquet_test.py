"""Reading parquet rows: multilingual names, list tags, and what is refused."""

from decimal import Decimal

from pantry.off_parquet import _diet, _name, _read

ROW = {
    "code": "8850643003416",
    "name_en": "Por Kwan Sour And Spicy Sauce",
    "name_main": None,
    "name_any": "Por Kwan",
    "brands": "Por Kwan",
    "analysis": ["en:palm-oil-free", "en:vegan", "en:vegetarian"],
    "kcal": 300.0,
    "protein": 6.67,
    "fat": 13.33,
    "carbs": 40.0,
    "fiber": 0.0,
    "sugar": 26.67,
    "sodium": 1.6,
}


class TestName:
    """English first, then any language the product states."""

    def test_the_english_name_wins(self) -> None:
        assert _name(ROW) == "Por Kwan Sour And Spicy Sauce"

    def test_a_japanese_only_name_is_still_a_name(self) -> None:
        """The CSV leaves these blank, and the record was lost for it."""
        japanese = "フルグラ"
        row = {**ROW, "name_en": None, "name_main": None,
               "name_any": japanese}

        assert _name(row) == japanese

    def test_a_product_with_no_name_at_all(self) -> None:
        row = {**ROW, "name_en": None, "name_main": None, "name_any": None}

        assert _name(row) == ""

    def test_whitespace_is_not_a_name(self) -> None:
        row = {**ROW, "name_en": "   ", "name_main": None, "name_any": "Real"}

        assert _name(row) == "Real"


class TestDiet:
    """Tags arrive as a list, so membership is exact."""

    def test_vegan_wins_over_vegetarian(self) -> None:
        assert _diet(ROW) == "vegan"

    def test_an_unknown_status_is_not_a_verdict(self) -> None:
        """The substring trap the flattened CSV sets does not exist here."""
        row = {**ROW, "analysis": ["en:vegan-status-unknown"]}

        assert _diet(row) is None

    def test_no_tags_is_unknown(self) -> None:
        assert _diet({**ROW, "analysis": None}) is None


class TestRead:
    """Rows into records, and the ones that cannot become one."""

    def test_a_row_becomes_a_record(self) -> None:
        reaped = _read([ROW])

        [stored] = reaped.records
        assert stored["id"] == "8850643003416"
        assert stored["kcal"] == Decimal("300")
        assert stored["protein"] == Decimal("6.67")
        assert stored["grams"] == 100
        assert reaped.diets == {"8850643003416": "vegan"}
        assert reaped.matched == 1

    def test_a_reported_zero_survives(self) -> None:
        [stored] = _read([ROW]).records

        assert stored["fiber"] == 0

    def test_a_row_with_no_panel_still_yields_its_diet(self) -> None:
        """The two halves are independent, exactly as in the CSV reader."""
        bare = {**ROW, **{key: None for key in
                          ("kcal", "protein", "fat", "carbs",
                           "fiber", "sugar", "sodium")}}

        reaped = _read([bare])

        assert reaped.records == []
        assert reaped.diets == {"8850643003416": "vegan"}
        assert reaped.matched == 1

    def test_an_impossible_panel_is_dropped_not_raised(self) -> None:
        reaped = _read([{**ROW, "kcal": 6380.0}])

        assert reaped.records == []
        assert reaped.matched == 1

    def test_a_row_with_no_code_is_skipped(self) -> None:
        assert _read([{**ROW, "code": None}]).records == []

    def test_matched_counts_rows_not_records(self) -> None:
        """Present-but-unusable and absent are different facts."""
        reaped = _read([ROW, {**ROW, "code": "999", "name_en": None,
                              "name_main": None, "name_any": None}])

        assert len(reaped.records) == 1
        assert reaped.matched == 2
