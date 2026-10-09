"""Unit tests for product search by SKU, barcode, and name."""

from unittest.mock import Mock

from src.catalog.product.app.queries.get_products import (
    SearchProductsQuery,
    SearchProductsQueryHandler,
)
from src.catalog.product.domain.entities import Product
from src.catalog.product.domain.specifications import ProductBySearchTerm


# Specification tests
def test_search_term_matches_sku():
    """Test ProductBySearchTerm matches by exact SKU."""
    product = Product(id=1, sku="SKU-001", name="Laptop", barcode="1234567890")
    spec = ProductBySearchTerm(term="SKU-001")

    assert spec.is_satisfied_by(product) is True


def test_search_term_matches_barcode():
    """Test ProductBySearchTerm matches by exact barcode."""
    product = Product(id=1, sku="SKU-001", name="Laptop", barcode="1234567890")
    spec = ProductBySearchTerm(term="1234567890")

    assert spec.is_satisfied_by(product) is True


def test_search_term_matches_name():
    """Test ProductBySearchTerm matches by name (case-insensitive)."""
    product = Product(id=1, sku="SKU-001", name="Laptop Computer")
    spec = ProductBySearchTerm(term="laptop")

    assert spec.is_satisfied_by(product) is True


def test_search_term_no_match():
    """Test ProductBySearchTerm returns False when no match."""
    product = Product(id=1, sku="SKU-001", name="Laptop", barcode="1234567890")
    spec = ProductBySearchTerm(term="nonexistent")

    assert spec.is_satisfied_by(product) is False


def test_search_term_with_none_barcode():
    """Test ProductBySearchTerm handles product without barcode."""
    product = Product(id=1, sku="SKU-001", name="Laptop")
    spec = ProductBySearchTerm(term="some-barcode")

    assert spec.is_satisfied_by(product) is False


def test_search_term_sql_criteria():
    """Test ProductBySearchTerm generates SQL criteria."""
    spec = ProductBySearchTerm(term="SKU-001")
    criteria = spec.to_query_criteria()

    assert len(criteria) == 1


# Handler tests
def test_search_products_handler():
    """Test SearchProductsQueryHandler delegates to repository with spec."""
    mock_repo = Mock()
    products = [
        Product(id=1, sku="SKU-001", name="Laptop Computer"),
    ]
    mock_repo.filter_by_spec.return_value = products

    handler = SearchProductsQueryHandler(mock_repo)
    result = handler.handle(SearchProductsQuery(search_term="SKU-001"))

    assert len(result) == 1
    assert result[0]["sku"] == "SKU-001"
    mock_repo.filter_by_spec.assert_called_once()


def test_search_products_handler_empty_results():
    """Test SearchProductsQueryHandler returns empty list when no matches."""
    mock_repo = Mock()
    mock_repo.filter_by_spec.return_value = []

    handler = SearchProductsQueryHandler(mock_repo)
    result = handler.handle(SearchProductsQuery(search_term="nonexistent"))

    assert result == []


def test_search_products_handler_respects_limit():
    """Test SearchProductsQueryHandler passes limit to repository."""
    mock_repo = Mock()
    mock_repo.filter_by_spec.return_value = []

    handler = SearchProductsQueryHandler(mock_repo)
    handler.handle(SearchProductsQuery(search_term="test", limit=5))

    _, kwargs = mock_repo.filter_by_spec.call_args
    assert kwargs["limit"] == 5


def test_search_term_matches_part_of_the_sku():
    product = Product(id=1, sku="LAP-001", name="Portátil", barcode=None)

    assert ProductBySearchTerm(term="lap").is_satisfied_by(product) is True
