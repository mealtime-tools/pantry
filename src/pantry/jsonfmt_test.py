"""The bytes this serializer writes, against what `JSON.stringify` writes."""

from decimal import Decimal

import pytest

from pantry.jsonfmt import dumps, format_number

# Every positional and exponential form ECMAScript's Number::toString takes,
# with the string `JSON.stringify` produces for it.
_FORMS = (
    ("0", "0"),
    ("-0", "0"),
    ("0.00", "0"),
    ("239.0", "239"),
    ("0.28", "0.28"),
    ("-0.5", "-0.5"),
    ("0.00001", "0.00001"),
    ("0.000001", "0.000001"),
    ("1e-7", "1e-7"),
    ("1.5e-9", "1.5e-9"),
    ("1e20", "100000000000000000000"),
    ("1e21", "1e+21"),
    ("1.5e21", "1.5e+21"),
)


@pytest.mark.parametrize(("stated", "written"), _FORMS)
def test_a_decimal_is_written_in_the_form_javascript_writes_it(
    stated: str, written: str
) -> None:
    assert format_number(Decimal(stated)) == written


def test_a_decimal_keeps_the_digits_it_was_given_and_drops_the_padding() -> (
    None
):
    """Quantising to six places must not put trailing zeros on the wire."""
    assert format_number(Decimal("0.280000")) == "0.28"
    assert format_number(Decimal("100.000000")) == "100"


def test_a_float_is_refused_rather_than_written_with_its_noise() -> None:
    """A float has no digits of its own, so one arriving here is the bug."""
    with pytest.raises(TypeError):
        format_number(0.28)
    with pytest.raises(TypeError):
        dumps({"fat": 0.1 + 0.2})


def test_a_decimal_that_is_not_a_number_is_refused() -> None:
    for value in ("nan", "inf", "-inf"):
        with pytest.raises(ValueError):
            format_number(Decimal(value))


def test_a_record_serializes_with_no_spaces_and_in_the_order_given() -> None:
    record = {
        "id": "1",
        "name": "Cocoa",
        "kcal": Decimal("391"),
        "fat": Decimal("2.80"),
        "grams": 100,
        "basis": None,
        "held": True,
    }

    assert dumps(record) == (
        '{"id":"1","name":"Cocoa","kcal":391,"fat":2.8,'
        '"grams":100,"basis":null,"held":true}'
    )
