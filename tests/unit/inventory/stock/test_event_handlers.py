"""Unit tests for Stock event handlers"""

from unittest.mock import Mock, patch

import pytest

from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.events import MovementCreated
from src.inventory.stock.domain.entities import Stock
from src.inventory.stock.domain.events import StockCreated, StockUpdated
from src.inventory.stock.domain.exceptions import InsufficientStockError
from src.inventory.stock.infra.event_handlers import handle_movement_created
from src.shared.infra.events.event_bus import EventBus


@pytest.fixture(autouse=True)
def clear_event_bus():
    """Clear event bus before each test"""
    EventBus.clear()
    yield
    EventBus.clear()


@patch("src.inventory.stock.infra.event_handlers.create_sync_scope")
def test_handle_movement_created_creates_new_stock(mock_create_scope):
    """Test that MovementCreated event creates new stock when none exists"""
    mock_repo = Mock()
    mock_repo.first_for_update.return_value = None

    new_stock = Stock(id=1, product_id=10, quantity=5)
    mock_repo.create.return_value = new_stock

    mock_scope = Mock()
    mock_scope.get.return_value = mock_repo
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    events_received = []

    def event_listener(event):
        events_received.append(event)

    EventBus.subscribe(StockCreated, event_listener)

    event = MovementCreated(
        aggregate_id=1,
        product_id=10,
        quantity=5,
        type=MovementType.IN.value,
        reason="Initial stock",
    )

    handle_movement_created(event)

    mock_repo.first_for_update.assert_called_once_with(product_id=10, location_id=None)
    mock_repo.create.assert_called_once()

    created_stock = mock_repo.create.call_args[0][0]
    assert created_stock.product_id == 10
    assert created_stock.quantity == 5

    assert len(events_received) == 1
    stock_event = events_received[0]
    assert isinstance(stock_event, StockCreated)
    assert stock_event.aggregate_id == 1
    assert stock_event.product_id == 10
    assert stock_event.quantity == 5


@patch("src.inventory.stock.infra.event_handlers.create_sync_scope")
def test_handle_movement_created_updates_existing_stock(mock_create_scope):
    """Test that MovementCreated event updates existing stock"""
    existing_stock = Stock(id=1, product_id=10, quantity=100)
    mock_repo = Mock()
    mock_repo.first_for_update.return_value = existing_stock

    updated_stock = Stock(id=1, product_id=10, quantity=105)
    mock_repo.update.return_value = updated_stock

    mock_scope = Mock()
    mock_scope.get.return_value = mock_repo
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    events_received = []

    def event_listener(event):
        events_received.append(event)

    EventBus.subscribe(StockUpdated, event_listener)

    event = MovementCreated(
        aggregate_id=2,
        product_id=10,
        quantity=5,
        type=MovementType.IN.value,
    )

    handle_movement_created(event)

    mock_repo.first_for_update.assert_called_once_with(product_id=10, location_id=None)
    mock_repo.update.assert_called_once()

    updated = mock_repo.update.call_args[0][0]
    assert updated.quantity == 105

    assert len(events_received) == 1
    stock_event = events_received[0]
    assert isinstance(stock_event, StockUpdated)
    assert stock_event.aggregate_id == 1
    assert stock_event.product_id == 10
    assert stock_event.old_quantity == 100
    assert stock_event.new_quantity == 105


@patch("src.inventory.stock.infra.event_handlers.create_sync_scope")
def test_handle_movement_created_decreases_stock_on_out(mock_create_scope):
    """Test that OUT movement decreases stock"""
    existing_stock = Stock(id=1, product_id=10, quantity=100)
    mock_repo = Mock()
    mock_repo.first_for_update.return_value = existing_stock

    updated_stock = Stock(id=1, product_id=10, quantity=95)
    mock_repo.update.return_value = updated_stock

    mock_scope = Mock()
    mock_scope.get.return_value = mock_repo
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    event = MovementCreated(
        aggregate_id=3,
        product_id=10,
        quantity=-5,
        type=MovementType.OUT.value,
    )

    handle_movement_created(event)

    mock_repo.first_for_update.assert_called_once_with(product_id=10, location_id=None)
    mock_repo.update.assert_called_once()

    updated = mock_repo.update.call_args[0][0]
    assert updated.quantity == 95


@patch("src.inventory.stock.infra.event_handlers.create_sync_scope")
def test_handle_movement_created_insufficient_stock_raises(mock_create_scope):
    """Test that insufficient stock raises exception"""
    existing_stock = Stock(id=1, product_id=10, quantity=3)
    mock_repo = Mock()
    mock_repo.first_for_update.return_value = existing_stock

    mock_scope = Mock()
    mock_scope.get.return_value = mock_repo
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    event = MovementCreated(
        aggregate_id=4,
        product_id=10,
        quantity=-5,
        type=MovementType.OUT.value,
    )

    with pytest.raises(InsufficientStockError) as exc_info:
        handle_movement_created(event)

    assert exc_info.value.data["product_id"] == 10
    mock_repo.update.assert_not_called()


@patch("src.inventory.stock.infra.event_handlers.create_sync_scope")
def test_handle_movement_created_out_without_stock_raises(mock_create_scope):
    """An OUT where the location has no stock row is rejected, not stored as
    a row with negative stock"""
    mock_repo = Mock()
    mock_repo.first_for_update.return_value = None

    mock_scope = Mock()
    mock_scope.get.return_value = mock_repo
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    event = MovementCreated(
        aggregate_id=5,
        product_id=10,
        quantity=-5,
        type=MovementType.OUT.value,
        location_id=3,
    )

    with pytest.raises(InsufficientStockError) as exc_info:
        handle_movement_created(event)

    assert exc_info.value.data == {"product_id": 10, "quantity": -5}
    mock_repo.create.assert_not_called()


@patch("src.inventory.stock.infra.event_handlers.create_sync_scope")
def test_handle_movement_created_out_cannot_take_reserved_units(mock_create_scope):
    existing_stock = Stock(id=1, product_id=10, quantity=10, reserved_quantity=8)
    mock_repo = Mock()
    mock_repo.first_for_update.return_value = existing_stock

    mock_scope = Mock()
    mock_scope.get.return_value = mock_repo
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    event = MovementCreated(
        aggregate_id=6,
        product_id=10,
        quantity=-3,
        type=MovementType.OUT.value,
    )

    with pytest.raises(InsufficientStockError):
        handle_movement_created(event)

    mock_repo.update.assert_not_called()


@patch("src.inventory.stock.infra.event_handlers.create_sync_scope")
def test_handle_movement_created_publishes_stock_created_event(mock_create_scope):
    """Test that StockCreated event is published when creating new stock"""
    mock_repo = Mock()
    mock_repo.first_for_update.return_value = None

    new_stock = Stock(id=1, product_id=10, quantity=5)
    mock_repo.create.return_value = new_stock

    mock_scope = Mock()
    mock_scope.get.return_value = mock_repo
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    events_received = []

    def event_listener(event: StockCreated):
        events_received.append(event)

    EventBus.subscribe(StockCreated, event_listener)

    event = MovementCreated(
        aggregate_id=1,
        product_id=10,
        quantity=5,
        type=MovementType.IN.value,
    )

    handle_movement_created(event)

    assert len(events_received) == 1
    stock_event = events_received[0]
    assert stock_event.aggregate_id == 1
    assert stock_event.product_id == 10
    assert stock_event.quantity == 5
    assert stock_event.location_id is None


@patch("src.inventory.stock.infra.event_handlers.create_sync_scope")
def test_handle_movement_created_publishes_stock_updated_event(mock_create_scope):
    """Test that StockUpdated event is published when updating stock"""
    existing_stock = Stock(id=1, product_id=10, quantity=100)
    mock_repo = Mock()
    mock_repo.first_for_update.return_value = existing_stock

    updated_stock = Stock(id=1, product_id=10, quantity=105)
    mock_repo.update.return_value = updated_stock

    mock_scope = Mock()
    mock_scope.get.return_value = mock_repo
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    events_received = []

    def event_listener(event: StockUpdated):
        events_received.append(event)

    EventBus.subscribe(StockUpdated, event_listener)

    event = MovementCreated(
        aggregate_id=2,
        product_id=10,
        quantity=5,
        type=MovementType.IN.value,
    )

    handle_movement_created(event)

    assert len(events_received) == 1
    stock_event = events_received[0]
    assert stock_event.aggregate_id == 1
    assert stock_event.product_id == 10
    assert stock_event.old_quantity == 100
    assert stock_event.new_quantity == 105


@patch("src.inventory.stock.infra.event_handlers.create_sync_scope")
def test_handle_movement_created_with_location(mock_create_scope):
    """Test creating stock with location_id"""
    mock_repo = Mock()
    mock_repo.first_for_update.return_value = None

    new_stock = Stock(id=1, product_id=10, quantity=5, location_id=42)
    mock_repo.create.return_value = new_stock

    mock_scope = Mock()
    mock_scope.get.return_value = mock_repo
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    event = MovementCreated(
        aggregate_id=1,
        product_id=10,
        quantity=5,
        type=MovementType.IN.value,
    )

    handle_movement_created(event)

    created_stock = mock_repo.create.call_args[0][0]
    assert created_stock.product_id == 10
    assert created_stock.quantity == 5
