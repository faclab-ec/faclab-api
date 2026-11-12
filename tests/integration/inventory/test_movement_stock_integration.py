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
from src.inventory.stock.domain.events import StockCreated
from src.inventory.stock.infra.event_handlers import handle_movement_created
from src.shared.infra.events.event_bus import EventBus
from src.shared.infra.events.event_bus_publisher import EventBusPublisher
from tests.audit import FakeAuditTrail
from tests.costs import inventory_costs
from tests.quantities import FakeProductQuantities


@pytest.fixture(autouse=True)
def clear_event_bus():
    """Clear event bus before each test"""
    # Clear the event bus first
    EventBus.clear()

    # Register the stock event handler manually
    EventBus.subscribe(MovementCreated, handle_movement_created)

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

    new_stock = Stock(id=1, product_id=10, quantity=Decimal(10))
    mock_stock_repo.create.return_value = new_stock

    # Mock the scope context manager
    mock_scope = Mock()
    mock_scope.get.return_value = mock_stock_repo
    mock_stock_scope.return_value.__enter__.return_value = mock_scope

    # Movement to create
    created_movement = Movement(
        id=1,
        product_id=10,
        quantity=Decimal(10),
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
        mock_movement_repo,
        EventBusPublisher(),
        Mock(),
        FakeAuditTrail(),
        FakeProductQuantities(),
        mock_stock_repo,
        inventory_costs(),
    )
    command = CreateMovementCommand(
        product_id=10,
        quantity=Decimal(10),
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
            return Stock(
                id=1, product_id=10, quantity=Decimal(10)
            )  # After first movement
        elif call_count[0] == 3:
            return Stock(
                id=1, product_id=10, quantity=Decimal(20)
            )  # After second movement

    mock_stock_repo.first_for_update.side_effect = mock_first
    mock_stock_repo.create.return_value = Stock(
        id=1, product_id=10, quantity=Decimal(10)
    )
    mock_stock_repo.update.side_effect = [
        Stock(id=1, product_id=10, quantity=Decimal(20)),
        Stock(id=1, product_id=10, quantity=Decimal(15)),
    ]

    # Mock the scope context manager
    mock_scope = Mock()
    mock_scope.get.return_value = mock_stock_repo
    mock_stock_scope.return_value.__enter__.return_value = mock_scope

    # The handler's own lock of the row (for the cost) doesn't count the calls
    # of the stock handler this test follows
    handler = CreateMovementCommandHandler(
        mock_movement_repo,
        EventBusPublisher(),
        Mock(),
        FakeAuditTrail(),
        FakeProductQuantities(),
        Mock(first_for_update=Mock(return_value=None)),
        inventory_costs(),
    )

    # Movement 1: +10
    mock_movement_repo.create.return_value = Movement(
        id=1, product_id=10, quantity=Decimal(10), type=MovementType.IN
    )
    command1 = CreateMovementCommand(
        product_id=10, quantity=Decimal(10), type=MovementType.IN.value
    )
    handler.handle(command1)

    # Movement 2: +10 (total 20)
    mock_movement_repo.create.return_value = Movement(
        id=2, product_id=10, quantity=Decimal(10), type=MovementType.IN
    )
    command2 = CreateMovementCommand(
        product_id=10, quantity=Decimal(10), type=MovementType.IN.value
    )
    handler.handle(command2)

    # Movement 3: -5 (total 15)
    mock_movement_repo.create.return_value = Movement(
        id=3, product_id=10, quantity=Decimal(-5), type=MovementType.OUT
    )
    command3 = CreateMovementCommand(
        product_id=10, quantity=Decimal(-5), type=MovementType.OUT.value
    )
    handler.handle(command3)

    # Assert
    # 1 create + 2 updates
    assert mock_stock_repo.create.call_count == 1
    assert mock_stock_repo.update.call_count == 2
