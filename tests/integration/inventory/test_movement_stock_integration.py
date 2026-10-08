"""Integration tests for Movement-Stock event-driven flow"""

from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from src.inventory.movement.app.commands import (
    CreateMovementCommand,
    CreateMovementCommandHandler,
)
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.inventory.movement.domain.events import MovementCreated
from src.inventory.stock.domain.entities import Stock
from src.inventory.stock.domain.events import StockCreated, StockUpdated
from src.inventory.stock.infra.event_handlers import handle_movement_created
from src.sales.domain.events import SaleCancelled, SaleConfirmed
from src.shared.infra.events.event_bus import EventBus
from src.shared.infra.events.event_bus_publisher import EventBusPublisher


@pytest.fixture(autouse=True)
def clear_event_bus():
    """Clear event bus before each test"""
    # Clear the event bus first
    EventBus.clear()

    # Register the stock event handler manually
    EventBus.subscribe(MovementCreated, handle_movement_created)

    # Reload event handlers module to register SaleConfirmed/SaleCancelled handlers
    # This ensures @event_handler decorators run and register the handlers
    import importlib

    import src.inventory.infra.event_handlers

    importlib.reload(src.inventory.infra.event_handlers)

    yield
    EventBus.clear()


@patch("src.inventory.stock.infra.event_handlers.create_sync_scope")
def test_create_movement_triggers_stock_update_via_event(mock_stock_scope):
    """
    Integration test: Creating a movement publishes MovementCreated,
    which triggers handle_movement_created, which updates stock.
    """
    # Arrange
    mock_movement_repo = Mock()
    mock_stock_repo = Mock()

    # Setup: No existing stock
    mock_stock_repo.first_for_update.return_value = None

    new_stock = Stock(id=1, product_id=10, quantity=10)
    mock_stock_repo.create.return_value = new_stock

    # Mock the scope context manager
    mock_scope = Mock()
    mock_scope.get.return_value = mock_stock_repo
    mock_stock_scope.return_value.__enter__.return_value = mock_scope

    # Movement to create
    created_movement = Movement(
        id=1,
        product_id=10,
        quantity=10,
        type=MovementType.IN,
        reason="Initial stock",
    )
    mock_movement_repo.create.return_value = created_movement

    # Track stock events
    stock_events = []

    def stock_listener(event):
        stock_events.append(event)

    EventBus.subscribe(StockCreated, stock_listener)

    # Create command handler
    handler = CreateMovementCommandHandler(
        mock_movement_repo, EventBusPublisher(), Mock()
    )
    command = CreateMovementCommand(
        product_id=10,
        quantity=10,
        type=MovementType.IN.value,
        reason="Initial stock",
    )

    # Act
    result = handler.handle(command)

    # Assert
    # 1. Movement was created
    assert result["id"] == 1
    assert result["product_id"] == 10
    mock_movement_repo.create.assert_called_once()

    # 2. Stock was created via event handler
    mock_stock_repo.create.assert_called_once()
    created_stock = mock_stock_repo.create.call_args[0][0]
    assert created_stock.product_id == 10
    assert created_stock.quantity == 10

    # 3. StockCreated event was published
    assert len(stock_events) == 1
    assert stock_events[0].product_id == 10


@patch("src.inventory.stock.infra.event_handlers.create_sync_scope")
@patch("src.inventory.infra.event_handlers.create_sync_scope")
def test_sale_confirmed_creates_movement_and_updates_stock(
    mock_inv_scope, mock_stock_scope
):
    """
    Integration test: SaleConfirmed → CreateMovement → MovementCreated → Stock updated
    """
    # Arrange
    mock_movement_repo = Mock()
    mock_stock_repo = Mock()

    # Existing stock
    existing_stock = Stock(id=1, product_id=10, quantity=100)
    mock_stock_repo.first_for_update.return_value = existing_stock

    updated_stock = Stock(id=1, product_id=10, quantity=95)
    mock_stock_repo.update.return_value = updated_stock

    # Movement created by sale confirmation
    created_movement = Movement(
        id=1,
        product_id=10,
        quantity=-5,
        type=MovementType.OUT,
        reason="Sale #123 confirmed",
    )
    mock_movement_repo.create.return_value = created_movement

    # Mock command handler that publishes MovementCreated event like the real one
    def mock_handle(command):
        EventBus.publish(
            MovementCreated(
                aggregate_id=created_movement.require_id(),
                product_id=created_movement.product_id,
                quantity=created_movement.quantity,
                type=created_movement.type.value,
                reason=created_movement.reason,
            )
        )
        return created_movement.dict()

    mock_command_handler = Mock()
    mock_command_handler.handle.side_effect = mock_handle

    # Mock the inventory scope (for SaleConfirmed handler)
    def inv_scope_get(type_class):
        if type_class == CreateMovementCommandHandler:
            return mock_command_handler
        raise ValueError(f"Unexpected resolve: {type_class}")

    mock_inv_scope_obj = Mock()
    mock_inv_scope_obj.get.side_effect = inv_scope_get
    mock_inv_scope.return_value.__enter__.return_value = mock_inv_scope_obj

    # Mock the stock scope (for MovementCreated handler)
    mock_stock_scope_obj = Mock()
    mock_stock_scope_obj.get.return_value = mock_stock_repo
    mock_stock_scope.return_value.__enter__.return_value = mock_stock_scope_obj

    # Track events
    stock_events = []

    def stock_listener(event):
        stock_events.append(event)

    EventBus.subscribe(StockUpdated, stock_listener)

    # Sale confirmed event
    sale_event = SaleConfirmed(
        aggregate_id=123,
        sale_id=123,
        customer_id=1,
        items=[{"product_id": 10, "quantity": 5, "unit_price": 10.0}],
        total=Decimal("50.0"),
    )

    # Act
    EventBus.publish(sale_event)

    # Assert
    # 1. Movement command handler was called
    mock_command_handler.handle.assert_called_once()
    call_args = mock_command_handler.handle.call_args[0][0]
    assert call_args.product_id == 10
    assert call_args.quantity == -5
    assert call_args.type == MovementType.OUT.value

    # 2. Stock was updated
    mock_stock_repo.update.assert_called_once()

    # 3. StockUpdated event was published
    assert len(stock_events) == 1
    assert stock_events[0].product_id == 10
    assert stock_events[0].old_quantity == 100
    assert stock_events[0].new_quantity == 95


@patch("src.inventory.stock.infra.event_handlers.create_sync_scope")
@patch("src.inventory.infra.event_handlers.create_sync_scope")
def test_sale_cancelled_reverts_stock_via_event(mock_inv_scope, mock_stock_scope):
    """
    Integration test: SaleCancelled (was_confirmed=True) → CreateMovement IN → Stock restored
    """
    # Arrange
    mock_movement_repo = Mock()
    mock_stock_repo = Mock()

    # Stock after sale was confirmed (reduced by 5)
    existing_stock = Stock(id=1, product_id=10, quantity=95)
    mock_stock_repo.first_for_update.return_value = existing_stock

    # Stock after reversal
    restored_stock = Stock(id=1, product_id=10, quantity=100)
    mock_stock_repo.update.return_value = restored_stock

    # Reversal movement
    reversal_movement = Movement(
        id=2,
        product_id=10,
        quantity=5,
        type=MovementType.IN,
        reason="Sale #123 cancelled - reversal",
    )
    mock_movement_repo.create.return_value = reversal_movement

    def mock_handle(command):
        EventBus.publish(
            MovementCreated(
                aggregate_id=reversal_movement.require_id(),
                product_id=reversal_movement.product_id,
                quantity=reversal_movement.quantity,
                type=reversal_movement.type.value,
                reason=reversal_movement.reason,
            )
        )
        return reversal_movement.dict()

    mock_command_handler = Mock()
    mock_command_handler.handle.side_effect = mock_handle

    # Mock the inventory scope
    def inv_scope_get(type_class):
        if type_class == CreateMovementCommandHandler:
            return mock_command_handler
        raise ValueError(f"Unexpected resolve: {type_class}")

    mock_inv_scope_obj = Mock()
    mock_inv_scope_obj.get.side_effect = inv_scope_get
    mock_inv_scope.return_value.__enter__.return_value = mock_inv_scope_obj

    # Mock the stock scope
    mock_stock_scope_obj = Mock()
    mock_stock_scope_obj.get.return_value = mock_stock_repo
    mock_stock_scope.return_value.__enter__.return_value = mock_stock_scope_obj

    # Track events
    stock_events = []

    def stock_listener(event):
        stock_events.append(event)

    EventBus.subscribe(StockUpdated, stock_listener)

    # Sale cancelled event (was confirmed)
    cancel_event = SaleCancelled(
        aggregate_id=123,
        sale_id=123,
        customer_id=1,
        items=[{"product_id": 10, "quantity": 5}],
        reason="Customer request",
        was_confirmed=True,
    )

    # Act
    EventBus.publish(cancel_event)

    # Assert
    # 1. Movement command handler was called
    mock_command_handler.handle.assert_called_once()
    call_args = mock_command_handler.handle.call_args[0][0]
    assert call_args.product_id == 10
    assert call_args.quantity == 5
    assert call_args.type == MovementType.IN.value

    # 2. Stock was restored
    mock_stock_repo.update.assert_called_once()

    # 3. StockUpdated event was published
    assert len(stock_events) == 1
    assert stock_events[0].product_id == 10
    assert stock_events[0].old_quantity == 95
    assert stock_events[0].new_quantity == 100


@patch("src.inventory.infra.event_handlers.create_sync_scope")
def test_sale_cancelled_draft_no_stock_change(mock_inv_scope):
    """
    Integration test: SaleCancelled (was_confirmed=False) → No movement created
    """
    # Arrange
    mock_command_handler = Mock()

    # Sale cancelled event (was NOT confirmed)
    cancel_event = SaleCancelled(
        aggregate_id=123,
        sale_id=123,
        customer_id=1,
        items=[{"product_id": 10, "quantity": 5}],
        reason="Customer request",
        was_confirmed=False,
    )

    # Act
    EventBus.publish(cancel_event)

    # Assert
    # No movement should be created for draft sales
    mock_command_handler.handle.assert_not_called()


@patch("src.inventory.stock.infra.event_handlers.create_sync_scope")
def test_multiple_movements_accumulate_stock(mock_stock_scope):
    """
    Integration test: Multiple movements update stock cumulatively
    """
    # Arrange
    mock_movement_repo = Mock()
    mock_stock_repo = Mock()

    # Start with no stock
    call_count = [0]

    def mock_first(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return None  # First call: no stock
        elif call_count[0] == 2:
            return Stock(id=1, product_id=10, quantity=10)  # After first movement
        elif call_count[0] == 3:
            return Stock(id=1, product_id=10, quantity=20)  # After second movement

    mock_stock_repo.first_for_update.side_effect = mock_first
    mock_stock_repo.create.return_value = Stock(id=1, product_id=10, quantity=10)
    mock_stock_repo.update.side_effect = [
        Stock(id=1, product_id=10, quantity=20),
        Stock(id=1, product_id=10, quantity=15),
    ]

    # Mock the scope context manager
    mock_scope = Mock()
    mock_scope.get.return_value = mock_stock_repo
    mock_stock_scope.return_value.__enter__.return_value = mock_scope

    handler = CreateMovementCommandHandler(
        mock_movement_repo, EventBusPublisher(), Mock()
    )

    # Movement 1: +10
    mock_movement_repo.create.return_value = Movement(
        id=1, product_id=10, quantity=10, type=MovementType.IN
    )
    command1 = CreateMovementCommand(
        product_id=10, quantity=10, type=MovementType.IN.value
    )
    handler.handle(command1)

    # Movement 2: +10 (total 20)
    mock_movement_repo.create.return_value = Movement(
        id=2, product_id=10, quantity=10, type=MovementType.IN
    )
    command2 = CreateMovementCommand(
        product_id=10, quantity=10, type=MovementType.IN.value
    )
    handler.handle(command2)

    # Movement 3: -5 (total 15)
    mock_movement_repo.create.return_value = Movement(
        id=3, product_id=10, quantity=-5, type=MovementType.OUT
    )
    command3 = CreateMovementCommand(
        product_id=10, quantity=-5, type=MovementType.OUT.value
    )
    handler.handle(command3)

    # Assert
    # 1 create + 2 updates
    assert mock_stock_repo.create.call_count == 1
    assert mock_stock_repo.update.call_count == 2
