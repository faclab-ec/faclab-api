from decimal import Decimal

import pytest
from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

from src.shared.domain.quantity import (
    QuantityPrecisionError,
    decimals_of,
    ensure_quantity_decimals,
    format_quantity,
)
from src.shared.infra.middlewares import ERROR_CODE_TO_STATUS
from src.shared.infra.validators import QuantityNumber


@pytest.mark.parametrize(
    ("quantity", "decimals"),
    [
        (Decimal("3"), 0),
        (Decimal("3.000000"), 0),
        (Decimal("2.5"), 1),
        (Decimal("2.500000"), 1),
        (Decimal("1.25"), 2),
        (Decimal("0.000001"), 6),
        (Decimal("-2.5"), 1),
        (Decimal("1E+1"), 0),
    ],
)
def test_decimals_of_counts_significant_decimals(quantity, decimals):
    assert decimals_of(quantity) == decimals


@pytest.mark.parametrize(
    ("quantity", "text"),
    [
        (Decimal("2.500000"), "2.5"),
        (Decimal("10.000000"), "10"),
        (Decimal("1E+1"), "10"),
        (Decimal("0.000001"), "0.000001"),
        (Decimal("-3.000000"), "-3"),
        (7, "7"),
    ],
)
def test_format_quantity_drops_trailing_zeros(quantity, text):
    assert format_quantity(quantity) == text


def test_a_unit_without_decimals_rejects_a_fraction():
    with pytest.raises(QuantityPrecisionError) as error:
        ensure_quantity_decimals(Decimal("1.5"), 0, product_id=7)

    assert error.value.error_code == "QUANTITY_PRECISION_EXCEEDED"
    assert str(error.value) == "Product 7 takes whole numbers: 1.5 is not allowed"


def test_a_unit_takes_up_to_its_decimals():
    ensure_quantity_decimals(Decimal("2.50"), 1)
    ensure_quantity_decimals(Decimal("2.000"), 0)

    with pytest.raises(QuantityPrecisionError, match="at most 2 decimals"):
        ensure_quantity_decimals(Decimal("1.255"), 2)


def test_quantity_precision_answers_422():
    assert ERROR_CODE_TO_STATUS["QUANTITY_PRECISION_EXCEEDED"] == 422


class _Line(BaseModel):
    quantity: QuantityNumber = Field(gt=0)


@pytest.mark.parametrize("value", [2.5, "2.5", 3, "0.000001"])
def test_quantity_number_reads_numbers_and_strings(value):
    assert _Line(quantity=value).quantity == Decimal(str(value))


def test_quantity_number_is_a_json_number():
    line = _Line(quantity=Decimal("2.500000"))

    assert line.model_dump_json() == '{"quantity":2.5}'
    assert line.model_dump(mode="json") == {"quantity": 2.5}


def test_a_route_hands_the_command_a_decimal():
    """Routes build commands from model_dump(): a float would break the exact
    arithmetic of the stock (Decimal + float)"""
    assert _Line(quantity=2.5).model_dump() == {"quantity": Decimal("2.5")}


@pytest.mark.parametrize("value", ["1.1234567", "1234567890123", 0])
def test_quantity_number_rejects_what_the_database_cannot_keep(value):
    with pytest.raises(PydanticValidationError):
        _Line(quantity=value)
