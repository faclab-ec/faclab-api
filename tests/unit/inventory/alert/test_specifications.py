from typing import Any

from src.inventory.stock.domain.entities import Stock
from src.inventory.stock.domain.specifications import (
    LowStockProducts,
    OutOfStockProducts,
    ReorderPointProducts,
)


def _make_stock(**overrides) -> Stock:
    defaults: dict[str, Any] = {
        "id": 1,
        "product_id": 10,
        "quantity": 5,
    }
    defaults.update(overrides)
    return Stock(**defaults)


# ---------------------------------------------------------------------------
# LowStockProducts
# ---------------------------------------------------------------------------


def test_low_stock_is_satisfied_by_returns_false_without_product_data():
    stock = _make_stock(quantity=2)
    spec = LowStockProducts()
    assert spec.is_satisfied_by(stock) is False


def test_low_stock_to_query_criteria_returns_two_without_warehouse_id():
    spec = LowStockProducts()
    criteria = spec.to_query_criteria()
    assert len(criteria) == 2


def test_low_stock_to_query_criteria_returns_three_with_warehouse_id():
    spec = LowStockProducts(warehouse_id=1)
    criteria = spec.to_query_criteria()
    assert len(criteria) == 3


# ---------------------------------------------------------------------------
# OutOfStockProducts
# ---------------------------------------------------------------------------


def test_out_of_stock_is_satisfied_by_zero_quantity():
    stock = _make_stock(quantity=0)
    spec = OutOfStockProducts()
    assert spec.is_satisfied_by(stock) is True


def test_out_of_stock_not_satisfied_by_positive_quantity():
    stock = _make_stock(quantity=5)
    spec = OutOfStockProducts()
    assert spec.is_satisfied_by(stock) is False


def test_out_of_stock_to_query_criteria_returns_one_without_warehouse_id():
    spec = OutOfStockProducts()
    criteria = spec.to_query_criteria()
    assert len(criteria) == 1


def test_out_of_stock_to_query_criteria_returns_two_with_warehouse_id():
    spec = OutOfStockProducts(warehouse_id=1)
    criteria = spec.to_query_criteria()
    assert len(criteria) == 2


# ---------------------------------------------------------------------------
# ReorderPointProducts
# ---------------------------------------------------------------------------


def test_reorder_point_is_satisfied_by_returns_false_without_product_data():
    stock = _make_stock(quantity=3)
    spec = ReorderPointProducts()
    assert spec.is_satisfied_by(stock) is False


def test_reorder_point_to_query_criteria_returns_two_without_warehouse_id():
    spec = ReorderPointProducts()
    criteria = spec.to_query_criteria()
    assert len(criteria) == 2


def test_reorder_point_to_query_criteria_returns_three_with_warehouse_id():
    spec = ReorderPointProducts(warehouse_id=2)
    criteria = spec.to_query_criteria()
    assert len(criteria) == 3
