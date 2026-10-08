"""Unit tests for Stock query handlers"""

from unittest.mock import Mock

import pytest

from src.catalog.product.domain.entities import Product
from src.inventory.location.domain.entities import Location
from src.inventory.stock.app.queries import (
    GetAllStocksQuery,
    GetAllStocksQueryHandler,
    GetStockByIdQuery,
    GetStockByIdQueryHandler,
    GetStockByProductQuery,
    GetStockByProductQueryHandler,
)
from src.inventory.stock.domain.entities import Stock
from src.shared.domain.exceptions import NotFoundError


@pytest.fixture
def mock_stock_repo():
    """Mock repository for Stock"""
    repo = Mock()
    return repo


def _list_handler(stock_repo) -> GetAllStocksQueryHandler:
    product_repo = Mock()
    product_repo.get_by_ids.return_value = []
    location_repo = Mock()
    location_repo.get_by_ids.return_value = []
    return GetAllStocksQueryHandler(stock_repo, product_repo, location_repo)


def test_get_all_stocks_query_handler(mock_stock_repo):
    """Test getting all stocks"""
    stocks = [
        Stock(id=1, product_id=1, quantity=100),
        Stock(id=2, product_id=2, quantity=50),
    ]
    mock_stock_repo.paginate.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [s.dict() for s in stocks],
    }

    query = GetAllStocksQuery()
    handler = _list_handler(mock_stock_repo)

    result = handler.handle(query)

    assert len(result["items"]) == 2
    assert result["items"][0]["id"] == 1
    assert result["items"][0]["quantity"] == 100
    assert result["items"][1]["id"] == 2
    assert result["items"][1]["quantity"] == 50
    assert result["total"] == 2
    mock_stock_repo.paginate.assert_called_once_with(limit=None, offset=None)


def test_get_all_stocks_with_product_filter(mock_stock_repo):
    """Test getting stocks filtered by product_id"""
    stocks = [
        Stock(id=1, product_id=1, quantity=100),
    ]
    mock_stock_repo.paginate.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [s.dict() for s in stocks],
    }

    query = GetAllStocksQuery(product_id=1)
    handler = _list_handler(mock_stock_repo)

    result = handler.handle(query)

    assert len(result["items"]) == 1
    assert result["items"][0]["product_id"] == 1
    assert result["items"][0]["quantity"] == 100
    assert result["total"] == 1
    mock_stock_repo.paginate.assert_called_once_with(
        limit=None, offset=None, product_id=1
    )


def test_get_all_stocks_empty(mock_stock_repo):
    """Test getting all stocks when none exist"""
    mock_stock_repo.paginate.return_value = {
        "total": 0,
        "limit": None,
        "offset": None,
        "items": [],
    }

    query = GetAllStocksQuery()
    handler = _list_handler(mock_stock_repo)

    result = handler.handle(query)

    assert len(result["items"]) == 0
    assert result["total"] == 0
    mock_stock_repo.paginate.assert_called_once_with(limit=None, offset=None)


def test_get_all_stocks_with_pagination(mock_stock_repo):
    """Test getting stocks with pagination"""
    stocks = [
        Stock(id=1, product_id=1, quantity=100),
        Stock(id=2, product_id=2, quantity=50),
    ]
    mock_stock_repo.paginate.return_value = {
        "total": 2,
        "limit": 10,
        "offset": 5,
        "items": [s.dict() for s in stocks],
    }

    query = GetAllStocksQuery(limit=10, offset=5)
    handler = _list_handler(mock_stock_repo)

    result = handler.handle(query)

    assert len(result["items"]) == 2
    assert result["total"] == 2
    mock_stock_repo.paginate.assert_called_once_with(limit=10, offset=5)


def test_get_all_stocks_adds_product_and_location_names(mock_stock_repo):
    stocks = [
        Stock(id=1, product_id=1, quantity=100, location_id=5),
        Stock(id=2, product_id=2, quantity=50),
    ]
    mock_stock_repo.paginate.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [s.dict() for s in stocks],
    }
    product_repo = Mock()
    product_repo.get_by_ids.return_value = [
        Product(id=1, name="Cable HDMI", sku="HDMI-01")
    ]
    location_repo = Mock()
    location_repo.get_by_ids.return_value = [
        Location(id=5, warehouse_id=1, name="Estante A1", code="A1")
    ]
    handler = GetAllStocksQueryHandler(mock_stock_repo, product_repo, location_repo)

    result = handler.handle(GetAllStocksQuery())

    first, second = result["items"]
    assert first["product_name"] == "Cable HDMI"
    assert first["location_name"] == "Estante A1"
    # Product 2 was not found and stock 2 has no location
    assert second["product_name"] is None
    assert second["location_name"] is None
    # Stocks without a location don't add a None id to the lookup
    assert list(location_repo.get_by_ids.call_args.args[0]) == [5]


def test_get_stock_by_id_handler(mock_stock_repo):
    """Test getting a stock by ID"""
    stock = Stock(id=1, product_id=1, quantity=100, location_id=5)
    mock_stock_repo.get_by_id.return_value = stock

    query = GetStockByIdQuery(id=1)
    handler = GetStockByIdQueryHandler(mock_stock_repo)

    result = handler.handle(query)

    assert result is not None
    assert result["id"] == 1
    assert result["product_id"] == 1
    assert result["quantity"] == 100
    assert result["location_id"] == 5
    mock_stock_repo.get_by_id.assert_called_once_with(1)


def test_get_stock_by_id_not_found_raises(mock_stock_repo):
    """Test getting non-existent stock raises NotFoundError"""
    mock_stock_repo.get_by_id.return_value = None

    query = GetStockByIdQuery(id=999)
    handler = GetStockByIdQueryHandler(mock_stock_repo)

    with pytest.raises(NotFoundError):
        handler.handle(query)
    mock_stock_repo.get_by_id.assert_called_once_with(999)


def test_get_stock_by_product_handler(mock_stock_repo):
    """Test getting stock by product_id"""
    stock = Stock(id=1, product_id=1, quantity=100)
    mock_stock_repo.first.return_value = stock

    query = GetStockByProductQuery(product_id=1)
    handler = GetStockByProductQueryHandler(mock_stock_repo)

    result = handler.handle(query)

    assert result is not None
    assert result["product_id"] == 1
    assert result["quantity"] == 100
    mock_stock_repo.first.assert_called_once_with(product_id=1)


def test_get_stock_by_product_not_found_raises(mock_stock_repo):
    """Test getting stock for non-existent product raises NotFoundError"""
    mock_stock_repo.first.return_value = None

    query = GetStockByProductQuery(product_id=999)
    handler = GetStockByProductQueryHandler(mock_stock_repo)

    with pytest.raises(NotFoundError):
        handler.handle(query)
    mock_stock_repo.first.assert_called_once_with(product_id=999)
