"""Importing a USDA food: per 100 g, no inferred zeros, no leaked key."""

import json

import pytest
from agentcli import RemoteError, UsageError

from pantry.credentials import resolve_key
from pantry.providers.usda import UsdaProvider
from pantry.usda import fetch_food, to_product

# A trimmed real response. `foodNutrients` is per 100 g; `labelNutrients` is
# per 30 g serving, and reading it would under-report by 70%.
BRANDED = {
    "fdcId": 2476857,
    "description": "PROTEIN FLOUR",
    "brandName": "ARROWHEAD MILLS",
    "brandOwner": "The Hain Celestial Group, Inc.",
    "servingSize": 30.0,
    "servingSizeUnit": "g",
    "foodNutrients": [
        {"nutrient": {"id": 1008, "unitName": "kcal"}, "amount": 367.0},
        {"nutrient": {"id": 1003}, "amount": 33.33},
        {"nutrient": {"id": 1004}, "amount": 3.33},
        {"nutrient": {"id": 1005}, "amount": 50.0},
        {"nutrient": {"id": 1079}, "amount": 6.7},
        {"nutrient": {"id": 2000}, "amount": 3.33},
        {"nutrient": {"id": 1093}, "amount": 17.0},
    ],
    "labelNutrients": {"protein": {"value": 10.0}, "fat": {"value": 1.0}},
}


def test_nutrients_are_read_per_hundred_grams_not_per_serving() -> None:
    """The per-serving panel must never be the one that wins."""
    product = to_product(BRANDED)

    assert product["kcal"] == 367.0
    assert product["protein"] == 33.33
    assert product["fat"] == 3.33
    assert product["carbs"] == 50.0
    # The serving figures are a third of these; reading them would be silent.
    assert product["protein"] != 10.0


def test_sodium_is_kept_in_the_milligrams_usda_publishes() -> None:
    """Nutrient 1093 is mg per 100 g, which is already the stored unit."""
    assert to_product(BRANDED)["sodium"] == 17.0


def test_identity_brand_and_url_come_from_the_record() -> None:
    product = to_product(BRANDED)

    assert (product["source"], product["id"]) == ("usda", "2476857")
    assert product["name"] == "PROTEIN FLOUR"
    # brandName is what a person recognises, so it beats brandOwner.
    assert product["brand"] == "ARROWHEAD MILLS"
    assert product["url"].endswith("/food-details/2476857/nutrients")


def test_an_absent_macro_stays_absent_rather_than_becoming_zero() -> None:
    """An inferred zero would quietly under-count every recipe using it."""
    thin = dict(BRANDED)
    thin["foodNutrients"] = [
        {"nutrient": {"id": 1008}, "amount": 100.0},
        {"nutrient": {"id": 1003}, "amount": 5.0},
    ]

    product = to_product(thin)

    assert product["protein"] == 5.0
    assert "fat" not in product
    assert "carbs" not in product


def _with_protein(amount: object) -> dict:
    """A complete record whose only variable is the protein figure.

    Fat and carbohydrate are supplied so a storage refusal can only be about
    protein; a record missing a macro is refused for that instead, which would
    make the test below pass without proving anything.
    """
    # The protein amount is whatever the caller passed, junk included, so
    # the rows say so rather than being narrowed to the numeric ones.
    rows: list[dict[str, object]] = [
        {"nutrient": {"id": 1008}, "amount": 100.0},
        {"nutrient": {"id": 1004}, "amount": 1.0},
        {"nutrient": {"id": 1005}, "amount": 2.0},
        {"nutrient": {"id": 1003}, "amount": amount},
    ]

    thin: dict[str, object] = dict(BRANDED)
    thin["foodNutrients"] = rows
    return thin


@pytest.mark.parametrize("amount", [None, "33.3", True, {}, []])
def test_a_non_numeric_amount_is_dropped_not_coerced(amount: object) -> None:
    """`"33.3"` is a missing value; coercing it is how zeros creep in.

    `True` is included on purpose: it is an `int` in Python, so a bare
    `isinstance(x, (int, float))` would store it as 1 g of protein.
    """
    assert "protein" not in to_product(_with_protein(amount))


@pytest.mark.parametrize("amount", [float("nan"), float("inf")])
def test_a_non_finite_amount_is_refused_at_storage(
    amount: float, make_deps
) -> None:
    """These are genuinely numbers, so the record validator is what stops them.

    Dropping them here instead would turn a corrupt figure into a silently
    absent one, which is the same under-count by another route.
    """
    product = to_product(_with_protein(amount))
    assert "protein" in product

    with pytest.raises(Exception, match="protein|finite|number"):
        make_deps([]).store.add(product)


def test_energy_falls_back_to_kilojoules_then_refuses() -> None:
    in_kj = dict(BRANDED)
    in_kj["foodNutrients"] = [{"nutrient": {"id": 1062}, "amount": 1000.0}]
    assert to_product(in_kj)["kcal"] == 239.0

    without = dict(BRANDED)
    without["foodNutrients"] = [{"nutrient": {"id": 1003}, "amount": 5.0}]
    with pytest.raises(RemoteError, match="no energy"):
        to_product(without)


def test_a_refusal_never_repeats_the_key(monkeypatch) -> None:
    """The key travels in the query string, so no error may echo the url."""
    import urllib.error

    def refuse(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 403, "no", {}, None)

    with pytest.raises(RemoteError) as caught:
        fetch_food("2476857", "SUPERSECRETKEY", opener=refuse)

    assert "SUPERSECRETKEY" not in str(caught.value)
    assert "403" in str(caught.value)


def test_the_environment_beats_a_stale_env_file() -> None:
    assert resolve_key("explicit", env={"USDA_API_KEY": "from-env"}) == (
        "explicit"
    )
    assert resolve_key(env={"USDA_API_KEY": "from-env"}) == "from-env"

    with pytest.raises(UsageError, match="api-key-signup"):
        resolve_key(env={})


def test_a_held_record_is_not_re_requested(make_deps, run) -> None:
    """Same rule as a retailer page: what is on disk is not paid for twice."""
    held = {
        "source": "usda",
        "id": "2476857",
        "name": "Held",
        "brand": "",
        "kcal": 1.0,
        "protein": 0.0,
        "fat": 0.0,
        "carbs": 0.0,
    }
    deps = make_deps([held])

    # The injected opener fails the test if it is called at all, so reaching
    # this payload is itself the proof that nothing was requested.
    result = run(deps, "--json", "add", "usda:2476857")

    assert result.exit_code == 0
    payload = json.loads(result.output)["data"]
    assert payload["stored"] is False
    assert payload["product"]["name"] == "Held"


def test_the_provider_is_disabled_without_a_key_and_says_where_to_get_one(
    make_deps, run
) -> None:
    """Unconfigured is not a failure; being asked to acquire anyway is."""
    assert UsdaProvider(env={}).enabled is False
    assert UsdaProvider(env={"USDA_API_KEY": "k"}).enabled is True

    result = run(make_deps([]), "add", "usda:2476857")

    assert result.exit_code == 1
    assert "api-key-signup" in result.output


def test_an_imported_food_is_stored_per_hundred_grams(make_deps, run) -> None:
    class Response:
        def read(self):
            return json.dumps(BRANDED).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    deps = make_deps(
        [],
        usda_opener=lambda request, timeout=None: Response(),
        env={"USDA_API_KEY": "SUPERSECRETKEY"},
    )

    result = run(deps, "--json", "add", "usda:2476857")

    assert result.exit_code == 0
    payload = json.loads(result.output)["data"]
    assert payload["stored"] is True
    assert payload["product"]["protein"] == 33.33
    # The key travels in the query string, so nothing may echo it.
    assert "SUPERSECRETKEY" not in result.output


def test_a_reference_that_is_not_an_fdc_id_is_refused(make_deps, run) -> None:
    result = run(make_deps([]), "add", "usda:not-an-id")

    assert result.exit_code == 1
    assert "usda:<fdcId>" in result.output
