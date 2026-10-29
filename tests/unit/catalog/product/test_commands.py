"""Unit tests for catalog product command handlers."""

from unittest.mock import MagicMock, Mock

from src.catalog.product.app.commands import (
    CreateCategoryCommand,
    CreateCategoryCommandHandler,
    CreateProductCommand,
    CreateProductCommandHandler,
    DeleteCategoryCommand,
    DeleteCategoryCommandHandler,
    DeleteProductCommand,
    DeleteProductCommandHandler,
    UpdateCategoryCommand,
    UpdateCategoryCommandHandler,
    UpdateProductCommand,
    UpdateProductCommandHandler,
)
from src.catalog.product.domain.entities import Category, Product
from src.catalog.product.domain.events import CategoryCreated, ProductCreated
from tests.audit import FakeAuditTrail


# Product Command Tests
def test_create_product_command_handler():
    """Test CreateProductCommandHandler creates a product and publishes event."""
    mock_repo = Mock()
    created_product = Product(id=1, sku="TEST-001", name="Test Product", category_id=1)
    mock_repo.create.return_value = created_product

    handler = CreateProductCommandHandler(mock_repo, MagicMock(), FakeAuditTrail())
    command = CreateProductCommand(sku="TEST-001", name="Test Product", category_id=1)

    result = handler.handle(command)

    assert result["id"] == 1
    assert result["sku"] == "TEST-001"
    assert result["name"] == "Test Product"
    mock_repo.create.assert_called_once()


def test_create_product_publishes_event():
    """Test that CreateProductCommandHandler publishes ProductCreated event."""
    mock_repo = Mock()
    created_product = Product(id=1, sku="TEST-001", name="Test Product")
    mock_repo.create.return_value = created_product

    event_publisher = MagicMock()
    handler = CreateProductCommandHandler(mock_repo, event_publisher, FakeAuditTrail())
    handler.handle(CreateProductCommand(sku="TEST-001", name="Test Product"))

    event_publisher.publish.assert_called_once()
    published_event = event_publisher.publish.call_args[0][0]
    assert isinstance(published_event, ProductCreated)
    assert published_event.product_id == 1
    assert published_event.sku == "TEST-001"


def test_update_product_command_handler():
    """Test UpdateProductCommandHandler updates a product and publishes event."""
    mock_repo = Mock()
    existing_product = Product(id=1, sku="OLD-001", name="Old Name")
    updated_product = Product(id=1, sku="NEW-001", name="New Name")
    mock_repo.get_by_id.return_value = existing_product
    mock_repo.update.return_value = updated_product

    handler = UpdateProductCommandHandler(mock_repo, MagicMock(), FakeAuditTrail())
    command = UpdateProductCommand(product_id=1, sku="NEW-001", name="New Name")

    result = handler.handle(command)

    assert result["id"] == 1
    assert result["sku"] == "NEW-001"
    assert result["name"] == "New Name"
    mock_repo.update.assert_called_once()


def test_delete_product_command_handler():
    """Test DeleteProductCommandHandler deletes a product and publishes event."""
    mock_repo = Mock()

    handler = DeleteProductCommandHandler(mock_repo, MagicMock(), FakeAuditTrail())
    command = DeleteProductCommand(product_id=1)

    result = handler.handle(command)

    assert result is None
    mock_repo.delete.assert_called_once_with(1)


# Category Command Tests
def test_create_category_command_handler():
    """Test CreateCategoryCommandHandler creates a category and publishes event."""
    mock_repo = Mock()
    created_category = Category(
        id=1, name="Electronics", description="Electronic items"
    )
    mock_repo.create.return_value = created_category

    handler = CreateCategoryCommandHandler(mock_repo, MagicMock())
    command = CreateCategoryCommand(name="Electronics", description="Electronic items")

    result = handler.handle(command)

    assert result["id"] == 1
    assert result["name"] == "Electronics"
    assert result["description"] == "Electronic items"
    mock_repo.create.assert_called_once()


def test_create_category_publishes_event():
    """Test that CreateCategoryCommandHandler publishes CategoryCreated event."""
    mock_repo = Mock()
    created_category = Category(
        id=1, name="Electronics", description="Electronic items"
    )
    mock_repo.create.return_value = created_category

    event_publisher = MagicMock()
    handler = CreateCategoryCommandHandler(mock_repo, event_publisher)
    handler.handle(CreateCategoryCommand(name="Electronics"))

    event_publisher.publish.assert_called_once()
    published_event = event_publisher.publish.call_args[0][0]
    assert isinstance(published_event, CategoryCreated)
    assert published_event.category_id == 1
    assert published_event.name == "Electronics"


def test_update_category_command_handler():
    """Test UpdateCategoryCommandHandler updates a category and publishes event."""
    mock_repo = Mock()
    existing_category = Category(id=1, name="Old Name", description="Old desc")
    updated_category = Category(id=1, name="New Name", description="New desc")
    mock_repo.get_by_id.return_value = existing_category
    mock_repo.update.return_value = updated_category

    handler = UpdateCategoryCommandHandler(mock_repo, MagicMock())
    command = UpdateCategoryCommand(
        category_id=1, name="New Name", description="New desc"
    )

    result = handler.handle(command)

    assert result["id"] == 1
    assert result["name"] == "New Name"
    assert result["description"] == "New desc"
    mock_repo.update.assert_called_once()


def test_delete_category_command_handler():
    """Test DeleteCategoryCommandHandler deletes a category and publishes event."""
    mock_repo = Mock()

    handler = DeleteCategoryCommandHandler(mock_repo, MagicMock())
    command = DeleteCategoryCommand(category_id=1)

    result = handler.handle(command)

    assert result is None
    mock_repo.delete.assert_called_once_with(1)
