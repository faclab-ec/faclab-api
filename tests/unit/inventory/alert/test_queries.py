from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock

from src.catalog.product.domain.entities import Product
from src.inventory.alert.app.queries.alerts import (
    GetExpiringLotsAlertsQuery,
    GetExpiringLotsAlertsQueryHandler,
    GetLowStockAlertsQuery,
    GetLowStockAlertsQueryHandler,
    GetOutOfStockAlertsQuery,
    GetOutOfStockAlertsQueryHandler,
    GetReorderPointAlertsQuery,
    GetReorderPointAlertsQueryHandler,
)
from src.inventory.alert.domain.types import AlertType
from src.inventory.lot.domain.entities import Lot
from src.inventory.stock.domain.entities import Stock


def _make_product(**overrides) -> Product:
    defaults: dict[str, Any] = {
        "id": 1,
        "name": "Test Product",
        "sku": "SKU-001",
        "is_service": False,
        "min_stock": 10,
        "reorder_point": 20,
    }
    defaults.update(overrides)
    return Product(**defaults)


def _make_stock(**overrides) -> Stock:
    defaults: dict[str, Any] = {
        "id": 1,
        "product_id": 1,
        "quantity": 5,
    }
    defaults.update(overrides)
    return Stock(**defaults)


def _make_lot(**overrides) -> Lot:
    defaults: dict[str, Any] = {
        "id": 1,
        "product_id": 1,
        "lot_number": "LOT-001",
        "initial_quantity": 100,
        "current_quantity": 50,
    }
    defaults.update(overrides)
    return Lot(**defaults)


# ---------------------------------------------------------------------------
# GetLowStockAlertsQueryHandler
# ---------------------------------------------------------------------------


def test_low_stock_returns_alerts_with_correct_type():
    stock = _make_stock(quantity=5)
    product = _make_product(min_stock=10)
    stock_repo = MagicMock()
    stock_repo.filter_by_spec.return_value = [stock]
    product_repo = MagicMock()
    product_repo.get_by_id.return_value = product
    handler = GetLowStockAlertsQueryHandler(stock_repo, product_repo)

    result = handler.handle(GetLowStockAlertsQuery())

    assert len(result) == 1
    assert result[0]["type"] == AlertType.LOW_STOCK
    assert result[0]["current_quantity"] == 5
    assert result[0]["threshold"] == 10


def test_low_stock_excludes_service_products():
    stock = _make_stock(quantity=0)
    service_product = _make_product(is_service=True)
    stock_repo = MagicMock()
    stock_repo.filter_by_spec.return_value = [stock]
    product_repo = MagicMock()
    product_repo.get_by_id.return_value = service_product
    handler = GetLowStockAlertsQueryHandler(stock_repo, product_repo)

    result = handler.handle(GetLowStockAlertsQuery())

    assert result == []


def test_low_stock_returns_empty_when_no_stocks():
    stock_repo = MagicMock()
    stock_repo.filter_by_spec.return_value = []
    product_repo = MagicMock()
    handler = GetLowStockAlertsQueryHandler(stock_repo, product_repo)

    result = handler.handle(GetLowStockAlertsQuery())

    assert result == []


def test_low_stock_sets_warehouse_id_from_query():
    stock = _make_stock(quantity=3)
    product = _make_product(min_stock=10)
    stock_repo = MagicMock()
    stock_repo.filter_by_spec.return_value = [stock]
    product_repo = MagicMock()
    product_repo.get_by_id.return_value = product
    handler = GetLowStockAlertsQueryHandler(stock_repo, product_repo)

    result = handler.handle(GetLowStockAlertsQuery(warehouse_id=5))

    assert result[0]["warehouse_id"] == 5


# ---------------------------------------------------------------------------
# GetOutOfStockAlertsQueryHandler
# ---------------------------------------------------------------------------


def test_out_of_stock_returns_zero_quantity_and_threshold():
    stock = _make_stock(quantity=0)
    product = _make_product()
    stock_repo = MagicMock()
    stock_repo.filter_by_spec.return_value = [stock]
    product_repo = MagicMock()
    product_repo.get_by_id.return_value = product
    handler = GetOutOfStockAlertsQueryHandler(stock_repo, product_repo)

    result = handler.handle(GetOutOfStockAlertsQuery())

    assert len(result) == 1
    assert result[0]["type"] == AlertType.OUT_OF_STOCK
    assert result[0]["current_quantity"] == 0
    assert result[0]["threshold"] == 0


def test_out_of_stock_excludes_service_products():
    stock = _make_stock(quantity=0)
    service_product = _make_product(is_service=True)
    stock_repo = MagicMock()
    stock_repo.filter_by_spec.return_value = [stock]
    product_repo = MagicMock()
    product_repo.get_by_id.return_value = service_product
    handler = GetOutOfStockAlertsQueryHandler(stock_repo, product_repo)

    result = handler.handle(GetOutOfStockAlertsQuery())

    assert result == []


# ---------------------------------------------------------------------------
# GetReorderPointAlertsQueryHandler
# ---------------------------------------------------------------------------


def test_reorder_point_uses_reorder_point_as_threshold():
    stock = _make_stock(quantity=15)
    product = _make_product(reorder_point=20)
    stock_repo = MagicMock()
    stock_repo.filter_by_spec.return_value = [stock]
    product_repo = MagicMock()
    product_repo.get_by_id.return_value = product
    handler = GetReorderPointAlertsQueryHandler(stock_repo, product_repo)

    result = handler.handle(GetReorderPointAlertsQuery())

    assert len(result) == 1
    assert result[0]["type"] == AlertType.REORDER_POINT
    assert result[0]["threshold"] == 20


def test_reorder_point_excludes_service_products():
    stock = _make_stock(quantity=5)
    service_product = _make_product(is_service=True)
    stock_repo = MagicMock()
    stock_repo.filter_by_spec.return_value = [stock]
    product_repo = MagicMock()
    product_repo.get_by_id.return_value = service_product
    handler = GetReorderPointAlertsQueryHandler(stock_repo, product_repo)

    result = handler.handle(GetReorderPointAlertsQuery())

    assert result == []


# ---------------------------------------------------------------------------
# GetExpiringLotsAlertsQueryHandler
# ---------------------------------------------------------------------------


def test_expiring_lots_returns_expiring_soon_type():
    expiry = date.today() + timedelta(days=10)
    lot = _make_lot(expiration_date=expiry, current_quantity=50)
    product = _make_product()
    lot_repo = MagicMock()
    lot_repo.filter_by_spec.return_value = [lot]
    product_repo = MagicMock()
    product_repo.get_by_id.return_value = product
    handler = GetExpiringLotsAlertsQueryHandler(lot_repo, product_repo)

    result = handler.handle(GetExpiringLotsAlertsQuery(days=30))

    assert len(result) == 1
    assert result[0]["type"] == AlertType.EXPIRING_SOON
    assert result[0]["lot_id"] == lot.id
    assert result[0]["days_to_expiry"] == (expiry - date.today()).days


def test_expiring_lots_excludes_service_products():
    expiry = date.today() + timedelta(days=5)
    lot = _make_lot(expiration_date=expiry, current_quantity=10)
    service_product = _make_product(is_service=True)
    lot_repo = MagicMock()
    lot_repo.filter_by_spec.return_value = [lot]
    product_repo = MagicMock()
    product_repo.get_by_id.return_value = service_product
    handler = GetExpiringLotsAlertsQueryHandler(lot_repo, product_repo)

    result = handler.handle(GetExpiringLotsAlertsQuery(days=30))

    assert result == []


def test_expiring_lots_returns_empty_when_no_lots():
    lot_repo = MagicMock()
    lot_repo.filter_by_spec.return_value = []
    product_repo = MagicMock()
    handler = GetExpiringLotsAlertsQueryHandler(lot_repo, product_repo)

    result = handler.handle(GetExpiringLotsAlertsQuery(days=30))

    assert result == []
