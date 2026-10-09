"""Unit tests for catalog product query handlers."""

from unittest.mock import ANY, Mock

import pytest

from src.catalog.product.app.queries import (
    GetAllCategoriesQuery,
    GetAllCategoriesQueryHandler,
    GetAllProductsQuery,
    GetAllProductsQueryHandler,
    GetCategoryByIdQuery,
    GetCategoryByIdQueryHandler,
    GetProductByIdQuery,
    GetProductByIdQueryHandler,
    SearchProductsQuery,
    SearchProductsQueryHandler,
)
from src.catalog.product.domain.entities import Category, Product
from src.shared.domain.exceptions import NotFoundError


# Product Query Tests
def test_get_all_products_query_handler():
    """Test GetAllProductsQueryHandler returns all products."""
    mock_repo = Mock()
    products = [
        Product(id=1, sku="SKU-001", name="Product 1"),
        Product(id=2, sku="SKU-002", name="Product 2"),
    ]
    mock_repo.paginate_by_spec.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [p.dict() for p in products],
    }

    handler = GetAllProductsQueryHandler(mock_repo)
    query = GetAllProductsQuery()

    result = handler.handle(query)

    assert len(result["items"]) == 2
    assert result["items"][0]["id"] == 1
    assert result["items"][1]["id"] == 2
    assert result["total"] == 2
    mock_repo.paginate_by_spec.assert_called_once_with(ANY, limit=None, offset=None)


def test_get_all_products_with_search_and_category():
    mock_repo = Mock()
    mock_repo.paginate_by_spec.return_value = {"total": 0, "items": []}

    GetAllProductsQueryHandler(mock_repo).handle(
        GetAllProductsQuery(category_id=3, search="lap")
    )

    spec = mock_repo.paginate_by_spec.call_args.args[0]
    assert spec.is_satisfied_by(Product(sku="X-1", name="Laptop", category_id=3))
    assert spec.is_satisfied_by(Product(sku="LAP-9", name="Otro", category_id=3))
    assert not spec.is_satisfied_by(Product(sku="X-1", name="Laptop", category_id=4))
    assert not spec.is_satisfied_by(Product(sku="X-1", name="Mouse", category_id=3))


def test_get_all_products_with_category_filter():
    """Test GetAllProductsQueryHandler filters by category."""
    mock_repo = Mock()
    products = [Product(id=1, sku="SKU-001", name="Product 1", category_id=1)]
    mock_repo.paginate_by_spec.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [p.dict() for p in products],
    }

    handler = GetAllProductsQueryHandler(mock_repo)
    query = GetAllProductsQuery(category_id=1)

    result = handler.handle(query)

    assert len(result["items"]) == 1
    assert result["items"][0]["category_id"] == 1
    assert result["total"] == 1
    mock_repo.paginate_by_spec.assert_called_once()


def test_get_product_by_id_handler():
    """Test GetProductByIdQueryHandler returns a product by ID."""
    mock_repo = Mock()
    product = Product(id=1, sku="SKU-001", name="Product 1")
    mock_repo.get_by_id.return_value = product

    handler = GetProductByIdQueryHandler(mock_repo)
    query = GetProductByIdQuery(product_id=1)

    result = handler.handle(query)

    assert result["id"] == 1
    assert result["sku"] == "SKU-001"
    mock_repo.get_by_id.assert_called_once_with(1)


def test_get_product_by_id_not_found_raises():
    """Test GetProductByIdQueryHandler raises NotFoundError when product not found."""
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = None

    handler = GetProductByIdQueryHandler(mock_repo)
    query = GetProductByIdQuery(product_id=999)

    with pytest.raises(NotFoundError):
        handler.handle(query)


def test_search_products_query_handler():
    """Test SearchProductsQueryHandler searches products by name."""
    mock_repo = Mock()
    products = [
        Product(id=1, sku="SKU-001", name="Laptop Computer"),
        Product(id=2, sku="SKU-002", name="Computer Mouse"),
    ]
    mock_repo.filter_by_spec.return_value = products

    handler = SearchProductsQueryHandler(mock_repo)
    query = SearchProductsQuery(search_term="Computer")

    result = handler.handle(query)

    assert len(result) == 2
    mock_repo.filter_by_spec.assert_called_once()


# Category Query Tests
def test_get_all_categories_query_handler():
    """Test GetAllCategoriesQueryHandler returns all categories."""
    mock_repo = Mock()
    categories = [
        Category(id=1, name="Electronics", description="Electronic items"),
        Category(id=2, name="Books", description="Book items"),
    ]
    mock_repo.paginate.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [c.dict() for c in categories],
    }

    handler = GetAllCategoriesQueryHandler(mock_repo)
    query = GetAllCategoriesQuery()

    result = handler.handle(query)

    assert len(result["items"]) == 2
    assert result["items"][0]["id"] == 1
    assert result["items"][1]["id"] == 2
    assert result["total"] == 2
    mock_repo.paginate.assert_called_once_with(limit=None, offset=None)


def test_get_category_by_id_handler():
    """Test GetCategoryByIdQueryHandler returns a category by ID."""
    mock_repo = Mock()
    category = Category(id=1, name="Electronics", description="Electronic items")
    mock_repo.get_by_id.return_value = category

    handler = GetCategoryByIdQueryHandler(mock_repo)
    query = GetCategoryByIdQuery(category_id=1)

    result = handler.handle(query)

    assert result["id"] == 1
    assert result["name"] == "Electronics"
    mock_repo.get_by_id.assert_called_once_with(1)


def test_get_category_by_id_not_found_raises():
    """Test GetCategoryByIdQueryHandler raises NotFoundError when category not found."""
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = None

    handler = GetCategoryByIdQueryHandler(mock_repo)
    query = GetCategoryByIdQuery(category_id=999)

    with pytest.raises(NotFoundError):
        handler.handle(query)
