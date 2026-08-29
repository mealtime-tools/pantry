"""Reading the export: what becomes a record, and what is left alone."""

from decimal import Decimal

from pantry.off_dump import diet, harvest, record, rows

COLUMNS = (
    "code",
    "product_name",
    "brands",
    "ingredients_analysis_tags",
    "energy-kcal_100g",
    "proteins_100g",
    "fat_100g",
    "carbohydrates_100g",
    "fiber_100g",
    "sugars_100g",
    "sodium_100g",
)

FULL = {
    "code": "8850643003416",
    "product_name": "Por Kwan Sour And Spicy Sauce",
    "brands": "Por Kwan",
    "ingredients_analysis_tags": "en:palm-oil-free,en:vegan,en:vegetarian",
    "energy-kcal_100g": "300",
    "proteins_100g": "6.67",
    "fat_100g": "13.33",
    "carbohydrates_100g": "40",
    "fiber_100g": "0",
    "sugars_100g": "26.67",
    "sodium_100g": "1.6",
}


def line(values: dict[str, str]) -> str:
    return "\t".join(values.get(column, "") for column in COLUMNS)


def export(*records: dict[str, str]) -> list[str]:
    """A whole export: the header, then one line per record."""
    return ["\t".join(COLUMNS), *(line(values) for values in records)]


class TestRows:
    """Turning lines into mappings without mangling them."""

    def test_a_header_names_the_fields(self) -> None:
        [row] = rows(export(FULL))

        assert row["code"] == "8850643003416"
        assert row["product_name"] == "Por Kwan Sour And Spicy Sauce"

    def test_a_quote_in_a_name_is_data_not_a_delimiter(self) -> None:
        """The export does not quote, so a reader must not unquote."""
        [row] = rows(export({**FULL, "product_name": 'Nature"s Kitchen Tofu'}))

        assert row["product_name"] == 'Nature"s Kitchen Tofu'

    def test_a_truncated_line_is_skipped_rather_than_guessed_at(self) -> None:
        lines = [*export(FULL), "8850643003416\tonly two fields"]

        assert len(list(rows(lines))) == 1

    def test_an_empty_export_yields_nothing(self) -> None:
        assert list(rows([])) == []


class TestDiet:
    """What the export concluded, and what it could not."""

    def test_vegan_wins_over_vegetarian(self) -> None:
        """A vegan product is a vegetarian one; the stricter answer is kept."""
        assert diet(FULL) == "vegan"

    def test_vegetarian_is_reported_on_its_own(self) -> None:
        row = {**FULL, "ingredients_analysis_tags": "en:vegetarian"}

        assert diet(row) == "vegetarian"

    def test_meat_is_reported_too(self) -> None:
        row = {**FULL, "ingredients_analysis_tags": "en:non-vegetarian"}

        assert diet(row) == "non-vegetarian"

    def test_an_unknown_status_is_absent_rather_than_assumed(self) -> None:
        row = {**FULL, "ingredients_analysis_tags": "en:vegan-status-unknown"}

        assert diet(row) is None

    def test_no_tags_at_all_is_unknown(self) -> None:
        assert diet({**FULL, "ingredients_analysis_tags": ""}) is None


class TestRecord:
    """What a row stores as, and what it refuses to store as."""

    def test_a_row_becomes_a_per_100_gram_record(self) -> None:
        stored = record(FULL)

        assert stored is not None
        assert stored["source"] == "openfoodfacts"
        assert stored["id"] == "8850643003416"
        assert stored["kcal"] == Decimal("300")
        assert stored["protein"] == Decimal("6.67")
        assert stored["grams"] == 100

    def test_a_reported_zero_survives_as_zero(self) -> None:
        """None of it is a fact; it must not read as unknown."""
        stored = record(FULL)

        assert stored is not None
        assert stored["fiber"] == 0

    def test_a_partial_panel_is_kept(self) -> None:
        """Some figures beat none, and the rest stay absent."""
        stored = record({**FULL, "fiber_100g": "", "sugars_100g": ""})

        assert stored is not None
        assert "fiber" not in stored
        assert stored["kcal"] == Decimal("300")

    def test_a_row_with_no_nutrient_at_all_is_not_a_panel(self) -> None:
        bare = {key: "" for key in COLUMNS}
        bare.update(code="123", product_name="Mystery")

        assert record(bare) is None

    def test_a_row_with_no_barcode_is_refused(self) -> None:
        assert record({**FULL, "code": ""}) is None

    def test_a_row_with_no_name_is_refused(self) -> None:
        assert record({**FULL, "product_name": ""}) is None

    def test_an_impossible_panel_is_dropped_not_raised(self) -> None:
        """The export carries rows stating 6380 kcal per 100 g. One of those
        must not end a download that takes minutes."""
        assert record({**FULL, "energy-kcal_100g": "6380"}) is None

    def test_an_unreadable_figure_is_absent_rather_than_zero(self) -> None:
        stored = record({**FULL, "proteins_100g": "unknown"})

        assert stored is not None
        assert "protein" not in stored


class TestHarvest:
    """One pass over the export, keeping only what was asked about."""

    def test_only_the_barcodes_asked_about_are_kept(self) -> None:
        other = {**FULL, "code": "9999999999999", "product_name": "Other"}

        reaped = harvest(export(FULL, other), {"8850643003416"})

        assert [p["id"] for p in reaped.records] == ["8850643003416"]
        assert set(reaped.diets) == {"8850643003416"}
        assert reaped.matched == 1

    def test_a_row_present_but_unusable_counts_as_matched(self) -> None:
        """Absent from the export and present-but-broken are different."""
        reaped = harvest(
            export({**FULL, "energy-kcal_100g": "6380"}), {"8850643003416"}
        )

        assert reaped.records == []
        assert reaped.matched == 1

    def test_a_diet_is_kept_even_where_there_is_no_panel(self) -> None:
        """The two halves are independent: either may be all the export has."""
        no_panel = {
            **{key: "" for key in COLUMNS},
            "code": "8850643003416",
            "product_name": "Mystery",
            "ingredients_analysis_tags": "en:vegetarian",
        }

        reaped = harvest(export(no_panel), {"8850643003416"})

        assert reaped.records == []
        assert reaped.diets == {"8850643003416": "vegetarian"}
        assert reaped.matched == 1

    def test_asking_about_nothing_finds_nothing(self) -> None:
        reaped = harvest(export(FULL), set())

        assert reaped.records == []
        assert reaped.diets == {}
        assert reaped.matched == 0
