"""Unit tests for Stock entity domain logic."""

from typing import Any

import pytest

from src.inventory.stock.domain.entities import Stock
from src.inventory.stock.domain.exceptions import InsufficientStockError

# --- Helpers ---


def _make_stock(**overrides) -> Stock:
    defaults: dict[str, Any] = {
        "id": 1,
        "product_id": 10,
        "quantity": 100,
        "location_id": None,
        "reserved_quantity": 0,
    }
    defaults.update(overrides)
    return Stock(**defaults)


# --- available_quantity ---


def test_available_quantity_no_reservations():
    stock = _make_stock(quantity=100, reserved_quantity=0)
    assert stock.available_quantity == 100


def test_available_quantity_with_reservations():
    stock = _make_stock(quantity=100, reserved_quantity=30)
    assert stock.available_quantity == 70


def test_available_quantity_fully_reserved():
    stock = _make_stock(quantity=50, reserved_quantity=50)
    assert stock.available_quantity == 0


def test_available_quantity_with_location():
    stock = _make_stock(quantity=200, reserved_quantity=50, location_id=5)
    assert stock.available_quantity == 150


# --- update_quantity (mutates in place) ---


def test_update_quantity_positive_delta_increases():
    stock = _make_stock(quantity=50)
    stock.update_quantity(30)

    assert stock.quantity == 80


def test_update_quantity_negative_delta_decreases():
    stock = _make_stock(quantity=100)
    stock.update_quantity(-25)

    assert stock.quantity == 75


def test_update_quantity_to_zero_is_allowed():
    stock = _make_stock(quantity=50)
    stock.update_quantity(-50)

    assert stock.quantity == 0


def test_update_quantity_preserves_other_fields():
    stock = _make_stock(quantity=100, location_id=5, reserved_quantity=10)
    stock.update_quantity(20)

    assert (stock.id, stock.product_id) == (1, 10)
    assert stock.location_id == 5
    assert stock.reserved_quantity == 10


def test_update_quantity_below_zero_raises_insufficient_stock():
    stock = _make_stock(quantity=10)

    with pytest.raises(InsufficientStockError):
        stock.update_quantity(-15)


def test_update_quantity_does_not_mutate_on_error():
    stock = _make_stock(quantity=5)

    with pytest.raises(InsufficientStockError):
        stock.update_quantity(-10)

    assert stock.quantity == 5  # Unchanged


def test_update_quantity_error_references_product_id():
    stock = _make_stock(product_id=42, quantity=3)

    with pytest.raises(InsufficientStockError) as exc_info:
        stock.update_quantity(-5)

    assert exc_info.value.data["product_id"] == 42


# --- location_id ---


def test_stock_with_location_id():
    stock = _make_stock(location_id=7)
    assert stock.location_id == 7


def test_stock_without_location_id():
    stock = _make_stock(location_id=None)
    assert stock.location_id is None


# --- reserved_quantity ---


def test_stock_default_reserved_quantity_is_zero():
    stock = Stock(product_id=1, quantity=100)
    assert stock.reserved_quantity == 0


def test_stock_with_reserved_quantity():
    stock = _make_stock(reserved_quantity=20)
    assert stock.reserved_quantity == 20


# --- reserve / release ---


def test_reserve_takes_from_available_quantity():
    stock = _make_stock(quantity=10, reserved_quantity=2)
    stock.reserve(5)

    assert stock.reserved_quantity == 7
    assert stock.available_quantity == 3


def test_reserve_more_than_available_raises():
    stock = _make_stock(quantity=10, reserved_quantity=6)

    with pytest.raises(InsufficientStockError):
        stock.reserve(5)

    assert stock.reserved_quantity == 6


def test_release_returns_reserved_units():
    stock = _make_stock(quantity=10, reserved_quantity=7)
    stock.release(5)

    assert stock.reserved_quantity == 2


def test_release_never_goes_below_zero():
    stock = _make_stock(quantity=10, reserved_quantity=3)
    stock.release(5)

    assert stock.reserved_quantity == 0
