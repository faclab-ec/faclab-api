"""Unit tests for POS product routes."""

from unittest.mock import Mock

from src.catalog.product.app.queries.get_products import SearchProductsQueryHandler
from src.catalog.product.domain.entities import Product
from src.pos.infra.routes import POSProductRouter
from src.shared.infra.validators import Meta


def test_search_returns_matching_products():
    """Test search route wraps the handler's list result in a ListResponse."""
    mock_repo = Mock()
    mock_repo.filter_by_spec.return_value = [
        Product(id=1, sku="SKU-001", name="Laptop"),
        Product(id=2, sku="SKU-002", name="Laptop Stand"),
    ]
    handler = SearchProductsQueryHandler(mock_repo)
    meta = Meta(request_id="req-1", timestamp="2026-01-01T00:00:00+00:00")

    response = POSProductRouter().search(
        handler=handler, term="laptop", limit=20, meta=meta
    )

    assert [p.sku for p in response.data] == ["SKU-001", "SKU-002"]


def test_search_returns_empty_list_when_no_matches():
    """Test search route returns an empty ListResponse when nothing matches."""
    mock_repo = Mock()
    mock_repo.filter_by_spec.return_value = []
    handler = SearchProductsQueryHandler(mock_repo)
    meta = Meta(request_id="req-1", timestamp="2026-01-01T00:00:00+00:00")

    response = POSProductRouter().search(
        handler=handler, term="nothing", limit=20, meta=meta
    )

    assert response.data == []
