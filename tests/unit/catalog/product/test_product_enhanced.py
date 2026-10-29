"""Unit tests for enhanced Product fields introduced in Phase 1."""

from dataclasses import replace
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from src.catalog.product.app.commands.create_product import (
    CreateProductCommand,
    CreateProductCommandHandler,
)
from src.catalog.product.app.commands.update_product import (
    UpdateProductCommand,
    UpdateProductCommandHandler,
)
from src.catalog.product.domain.entities import Product
from src.catalog.product.domain.events import ProductUpdated
from src.shared.domain.exceptions import NotFoundError
from tests.audit import FakeAuditTrail

# --- Helpers ---


def _make_product(**overrides) -> Product:
    defaults: dict[str, Any] = {
        "id": 1,
        "sku": "SKU-001",
        "name": "Test Product",
        "description": None,
        "barcode": None,
        "category_id": None,
        "unit_of_measure_id": None,
        "purchase_price": None,
        "sale_price": None,
        "is_active": True,
        "is_service": False,
        "min_stock": 0,
        "max_stock": None,
        "reorder_point": 0,
        "lead_time_days": None,
    }
    defaults.update(overrides)
    return Product(**defaults)


# --- Create: new fields ---


def test_create_product_with_all_new_fields():
    product = _make_product(
        barcode="7891234567890",
        purchase_price=Decimal("10.5000"),
        sale_price=Decimal("15.9900"),
        unit_of_measure_id=2,
        is_active=True,
        is_service=False,
        min_stock=5,
        max_stock=100,
        reorder_point=10,
        lead_time_days=7,
    )
    repo = Mock()
    repo.create.return_value = product
    handler = CreateProductCommandHandler(repo, MagicMock(), FakeAuditTrail())

    result = handler.handle(
        CreateProductCommand(
            sku="SKU-001",
            name="Test Product",
            barcode="7891234567890",
            purchase_price=Decimal("10.5000"),
            sale_price=Decimal("15.9900"),
            unit_of_measure_id=2,
            is_active=True,
            is_service=False,
            min_stock=5,
            max_stock=100,
            reorder_point=10,
            lead_time_days=7,
        )
    )

    assert result["barcode"] == "7891234567890"
    assert result["purchase_price"] == Decimal("10.5000")
    assert result["sale_price"] == Decimal("15.9900")
    assert result["unit_of_measure_id"] == 2
    assert result["is_active"] is True
    assert result["is_service"] is False
    assert result["min_stock"] == 5
    assert result["max_stock"] == 100
    assert result["reorder_point"] == 10
    assert result["lead_time_days"] == 7


def test_create_product_service_type():
    """Services (is_service=True) can be created."""
    product = _make_product(is_service=True, min_stock=0, reorder_point=0)
    repo = Mock()
    repo.create.return_value = product
    handler = CreateProductCommandHandler(repo, MagicMock(), FakeAuditTrail())

    result = handler.handle(
        CreateProductCommand(sku="SVC-001", name="Consulting", is_service=True)
    )

    assert result["is_service"] is True


def test_create_product_inactive():
    """Products can be created as inactive."""
    product = _make_product(is_active=False)
    repo = Mock()
    repo.create.return_value = product
    handler = CreateProductCommandHandler(repo, MagicMock(), FakeAuditTrail())

    result = handler.handle(
        CreateProductCommand(sku="SKU-001", name="Old Product", is_active=False)
    )

    assert result["is_active"] is False


def test_create_product_defaults_for_new_fields():
    """Default values for new fields are applied correctly."""
    product = _make_product()
    repo = Mock()
    repo.create.return_value = product
    handler = CreateProductCommandHandler(repo, MagicMock(), FakeAuditTrail())

    result = handler.handle(CreateProductCommand(sku="SKU-001", name="Simple Product"))

    assert result["barcode"] is None
    assert result["purchase_price"] is None
    assert result["sale_price"] is None
    assert result["unit_of_measure_id"] is None
    assert result["is_active"] is True
    assert result["is_service"] is False
    assert result["min_stock"] == 0
    assert result["max_stock"] is None
    assert result["reorder_point"] == 0
    assert result["lead_time_days"] is None


def test_create_product_passes_new_fields_to_entity():
    """Handler passes new fields correctly to the entity constructor."""
    repo = Mock()
    repo.create.side_effect = lambda e: replace(e, id=1)  # simulate persistence
    handler = CreateProductCommandHandler(repo, MagicMock(), FakeAuditTrail())

    handler.handle(
        CreateProductCommand(
            sku="SKU-001",
            name="Product",
            barcode="123456",
            purchase_price=Decimal("5.00"),
            unit_of_measure_id=3,
            min_stock=2,
            reorder_point=1,
        )
    )

    created = repo.create.call_args[0][0]
    assert created.barcode == "123456"
    assert created.purchase_price == Decimal("5.00")
    assert created.unit_of_measure_id == 3
    assert created.min_stock == 2
    assert created.reorder_point == 1


# --- Update: new fields ---


def test_update_product_with_new_fields():
    existing = _make_product()
    updated = _make_product(
        purchase_price=Decimal("20.00"),
        sale_price=Decimal("29.99"),
        min_stock=10,
        reorder_point=3,
        lead_time_days=14,
    )
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.update.return_value = updated
    handler = UpdateProductCommandHandler(repo, MagicMock(), FakeAuditTrail())

    result = handler.handle(
        UpdateProductCommand(
            product_id=1,
            sku="SKU-001",
            name="Test Product",
            purchase_price=Decimal("20.00"),
            sale_price=Decimal("29.99"),
            min_stock=10,
            reorder_point=3,
            lead_time_days=14,
        )
    )

    assert result["purchase_price"] == Decimal("20.00")
    assert result["sale_price"] == Decimal("29.99")
    assert result["min_stock"] == 10
    assert result["reorder_point"] == 3
    assert result["lead_time_days"] == 14


def test_update_product_tracks_new_field_changes_in_event():
    """ProductUpdated event payload includes changes in new fields."""
    existing = _make_product(min_stock=0, purchase_price=None)
    updated = _make_product(min_stock=5, purchase_price=Decimal("10.00"))
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.update.return_value = updated

    event_publisher = MagicMock()
    handler = UpdateProductCommandHandler(repo, event_publisher, FakeAuditTrail())
    handler.handle(
        UpdateProductCommand(
            product_id=1,
            sku="SKU-001",
            name="Test Product",
            min_stock=5,
            purchase_price=Decimal("10.00"),
        )
    )

    event_publisher.publish.assert_called_once()
    event = event_publisher.publish.call_args[0][0]
    assert isinstance(event, ProductUpdated)
    assert "min_stock" in event.changes
    assert event.changes["min_stock"]["old"] == 0
    assert event.changes["min_stock"]["new"] == 5
    assert "purchase_price" in event.changes
    assert event.changes["purchase_price"]["new"] == Decimal("10.00")


def test_update_product_deactivate():
    existing = _make_product(is_active=True)
    deactivated = _make_product(is_active=False)
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.update.return_value = deactivated
    handler = UpdateProductCommandHandler(repo, MagicMock(), FakeAuditTrail())

    result = handler.handle(
        UpdateProductCommand(
            product_id=1, sku="SKU-001", name="Test Product", is_active=False
        )
    )

    assert result["is_active"] is False


def test_update_product_not_found_raises():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = UpdateProductCommandHandler(repo, MagicMock(), FakeAuditTrail())

    with pytest.raises(NotFoundError):
        handler.handle(
            UpdateProductCommand(product_id=999, sku="SKU-001", name="Product")
        )


def test_update_product_no_changes_does_not_include_unchanged_fields_in_event():
    """If a field did not change, it should NOT appear in event.changes."""
    product = _make_product(min_stock=5, barcode="123")
    repo = Mock()
    repo.get_by_id.return_value = product
    repo.update.return_value = product

    event_publisher = MagicMock()
    handler = UpdateProductCommandHandler(repo, event_publisher, FakeAuditTrail())
    handler.handle(
        UpdateProductCommand(
            product_id=1,
            sku="SKU-001",
            name="Test Product",
            min_stock=5,
            barcode="123",
        )
    )

    event = event_publisher.publish.call_args[0][0]
    assert "min_stock" not in event.changes
    assert "barcode" not in event.changes


def test_update_product_set_barcode():
    existing = _make_product(barcode=None)
    updated = _make_product(barcode="9876543210123")
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.update.return_value = updated
    handler = UpdateProductCommandHandler(repo, MagicMock(), FakeAuditTrail())

    result = handler.handle(
        UpdateProductCommand(
            product_id=1,
            sku="SKU-001",
            name="Test Product",
            barcode="9876543210123",
        )
    )

    assert result["barcode"] == "9876543210123"


def test_update_product_with_unit_of_measure():
    existing = _make_product(unit_of_measure_id=None)
    updated = _make_product(unit_of_measure_id=5)
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.update.return_value = updated
    handler = UpdateProductCommandHandler(repo, MagicMock(), FakeAuditTrail())

    result = handler.handle(
        UpdateProductCommand(
            product_id=1,
            sku="SKU-001",
            name="Test Product",
            unit_of_measure_id=5,
        )
    )

    assert result["unit_of_measure_id"] == 5
