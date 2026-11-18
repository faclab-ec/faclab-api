"""Conventions of the public API (S6.3): stable order and `sort`, decimal
strings, UTC timestamps and the public error catalog."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.dialects import postgresql

from src.catalog.product.infra.models import ProductModel
from src.public_api.app.listing import PageRequest, ordering
from src.public_api.domain.exceptions import InvalidSortError
from src.public_api.infra.errors import public_error_code
from src.public_api.infra.types import (
    MoneyInput,
    QuantityInput,
    money_text,
    quantity_text,
    utc_naive,
    utc_text,
)

FIELDS = {
    "id": ProductModel.id,
    "name": ProductModel.name,
    "updatedAt": ProductModel.updated_at,
}


def _sql(order) -> list[str]:
    return [str(o.compile(dialect=postgresql.dialect())) for o in order]


def test_without_sort_the_id_orders():
    assert _sql(ordering(PageRequest(), FIELDS, ProductModel.id)) == ["products.id ASC"]


def test_a_sort_field_ends_with_the_id_in_its_direction():
    order = ordering(PageRequest(sort="-name"), FIELDS, ProductModel.id)

    assert _sql(order) == ["products.name DESC", "products.id DESC"]


def test_a_sync_without_sort_walks_by_update_time():
    page = PageRequest(updated_since=datetime(2026, 11, 1))

    assert _sql(ordering(page, FIELDS, ProductModel.id)) == [
        "products.updated_at ASC",
        "products.id ASC",
    ]


def test_a_field_outside_the_list_is_refused():
    with pytest.raises(InvalidSortError) as raised:
        ordering(PageRequest(sort="purchasePrice"), FIELDS, ProductModel.id)

    assert raised.value.error_code == "VALIDATION_ERROR"
    assert raised.value.extra == {"field": "sort"}


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("12.5"), "12.50"),
        (Decimal("100"), "100.00"),
        (Decimal("4.250000"), "4.25"),
        (Decimal("4.123456"), "4.123456"),
        (Decimal("0"), "0.00"),
    ],
)
def test_money_travels_with_its_cents(value, text):
    assert money_text(value) == text


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("3.000000"), "3"),
        (Decimal("2.500000"), "2.5"),
        (Decimal("100"), "100"),
        (Decimal("0.000001"), "0.000001"),
    ],
)
def test_quantities_travel_without_trailing_zeros(value, text):
    assert quantity_text(value) == text


def test_timestamps_are_utc_with_z():
    assert utc_text(datetime(2026, 11, 17, 15, 4, 5, 123999)) == (
        "2026-11-17T15:04:05.123Z"
    )
    quito = timezone(timedelta(hours=-5))
    assert utc_text(datetime(2026, 11, 17, 10, 4, 5, tzinfo=quito)) == (
        "2026-11-17T15:04:05.000Z"
    )
    assert utc_naive(datetime(2026, 11, 17, 10, tzinfo=quito)) == datetime(
        2026, 11, 17, 15
    )
    assert utc_naive(datetime(2026, 11, 17, 10, tzinfo=UTC)).tzinfo is None


class _Line(BaseModel):
    quantity: QuantityInput
    price: MoneyInput


def test_decimals_come_as_strings_or_integers():
    line = _Line.model_validate({"quantity": "2.5", "price": 3})

    assert (line.quantity, line.price) == (Decimal("2.5"), Decimal(3))


@pytest.mark.parametrize(
    "body",
    [
        {"quantity": 2.5, "price": "1"},
        {"quantity": "2.5", "price": 1.1},
        {"quantity": "0", "price": "1"},
        {"quantity": "1.0000001", "price": "1"},
        {"quantity": "1", "price": "-1"},
        {"quantity": True, "price": "1"},
    ],
    ids=["float-quantity", "float-price", "zero", "seven-decimals", "negative", "bool"],
)
def test_floats_and_bad_decimals_are_refused(body):
    with pytest.raises(ValidationError):
        _Line.model_validate(body)


@pytest.mark.parametrize(
    ("code", "status", "public"),
    [
        ("INSUFFICIENT_STOCK", 400, "INSUFFICIENT_STOCK"),
        ("CUSTOMER_TAX_ID_ALREADY_EXISTS", 409, "CUSTOMER_ALREADY_EXISTS"),
        ("POS_TERMINAL_INACTIVE", 409, "CONFLICT"),
        ("SALES_ERROR", 400, "BUSINESS_RULE_VIOLATION"),
        ("INTEGRITY_ERROR", 409, "CONFLICT"),
        ("HTTP_ERROR", 404, "NOT_FOUND"),
        ("HTTP_ERROR", 405, "BUSINESS_RULE_VIOLATION"),
        ("EMAIL_DELIVERY_FAILED", 502, "INTERNAL_ERROR"),
        ("TENANT_REQUIRED", 401, "INVALID_TOKEN"),
    ],
)
def test_an_integration_only_gets_codes_of_the_catalog(code, status, public):
    assert public_error_code(code, status) == public
