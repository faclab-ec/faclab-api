"""Unit tests for product search by SKU, barcode, and name."""

from unittest.mock import Mock

from src.catalog.product.app.queries.get_products import (
    SearchProductsQuery,
    SearchProductsQueryHandler,
)
from src.catalog.product.domain.entities import Product
from src.catalog.product.domain.specifications import ProductBySearchTerm
from tests.presentations import FakeProductPresentations
from tests.quantities import FakeProductQuantities


# Specification tests
def test_search_term_matches_sku():
    """Test ProductBySearchTerm matches by exact SKU."""
    product = Product(id=1, sku="SKU-001", name="Laptop")
    spec = ProductBySearchTerm(term="SKU-001")

    assert spec.is_satisfied_by(product) is True


def test_search_term_looks_for_the_barcode_in_the_presentations(in_tenant):
    """Barcodes live in the presentations (S5.2): only the SQL criteria see them"""
    (criteria,) = ProductBySearchTerm(term="1234567890").to_query_criteria()

    sql = str(criteria.compile(compile_kwargs={"literal_binds": True}))
    assert "EXISTS" in sql
    assert "product_presentations.barcode = '1234567890'" in sql
    assert "product_presentations.is_active IS true" in sql
    assert "product_presentations.tenant_id" in sql


def test_search_term_matches_name():
    """Test ProductBySearchTerm matches by name (case-insensitive)."""
    product = Product(id=1, sku="SKU-001", name="Laptop Computer")
    spec = ProductBySearchTerm(term="laptop")

    assert spec.is_satisfied_by(product) is True


def test_search_term_no_match():
    """Test ProductBySearchTerm returns False when no match."""
    product = Product(id=1, sku="SKU-001", name="Laptop")
    spec = ProductBySearchTerm(term="nonexistent")

    assert spec.is_satisfied_by(product) is False


def test_search_term_with_none_barcode():
    """Test ProductBySearchTerm handles product without barcode."""
    product = Product(id=1, sku="SKU-001", name="Laptop")
    spec = ProductBySearchTerm(term="some-barcode")

    assert spec.is_satisfied_by(product) is False


def test_search_term_sql_criteria(in_tenant):
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

    handler = SearchProductsQueryHandler(
        mock_repo, FakeProductQuantities(), FakeProductPresentations()
    )
    result = handler.handle(SearchProductsQuery(search_term="SKU-001"))

    assert len(result) == 1
    assert result[0]["sku"] == "SKU-001"
    mock_repo.filter_by_spec.assert_called_once()


def test_search_products_handler_empty_results():
    """Test SearchProductsQueryHandler returns empty list when no matches."""
    mock_repo = Mock()
    mock_repo.filter_by_spec.return_value = []

    handler = SearchProductsQueryHandler(
        mock_repo, FakeProductQuantities(), FakeProductPresentations()
    )
    result = handler.handle(SearchProductsQuery(search_term="nonexistent"))

    assert result == []


def test_search_products_handler_respects_limit():
    """Test SearchProductsQueryHandler passes limit to repository."""
    mock_repo = Mock()
    mock_repo.filter_by_spec.return_value = []

    handler = SearchProductsQueryHandler(
        mock_repo, FakeProductQuantities(), FakeProductPresentations()
    )
    handler.handle(SearchProductsQuery(search_term="test", limit=5))

    _, kwargs = mock_repo.filter_by_spec.call_args
    assert kwargs["limit"] == 5


def test_search_term_matches_part_of_the_sku():
    product = Product(id=1, sku="LAP-001", name="Portátil")

    assert ProductBySearchTerm(term="lap").is_satisfied_by(product) is True
