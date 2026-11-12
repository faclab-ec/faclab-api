"""Unit tests for Movement command handlers"""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, Mock

import pytest

from src.inventory.movement.app.commands import (
    CreateMovementCommand,
    CreateMovementCommandHandler,
)
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.inventory.movement.domain.events import MovementCreated
from src.inventory.movement.domain.exceptions import InvalidMovementTypeError
from src.inventory.stock.domain.entities import Stock
from src.shared.domain.quantity import QuantityPrecisionError
from tests.audit import FakeAuditTrail
from tests.costs import inventory_costs
from tests.quantities import FakeProductQuantities


def _stock_repo(stock=None):
    """The stock repository the handler locks the row with (none by default)"""
    repo = Mock()
    repo.first_for_update.return_value = stock
    return repo


@pytest.fixture
def mock_movement_repo():
    """Mock repository for Movement"""
    return Mock()


@pytest.fixture
def event_publisher():
    return MagicMock()


def test_create_movement_in_command_handler_success(
    mock_movement_repo, event_publisher
):
    """Test creating an IN movement successfully"""
    command = CreateMovementCommand(
        product_id=1,
        quantity=Decimal(10),
        type=MovementType.IN.value,
        reason="Purchase order #123",
    )

    mock_movement_repo.create.return_value = Movement(
        id=1,
        product_id=1,
        quantity=Decimal(10),
        type=MovementType.IN,
        reason="Purchase order #123",
    )

    handler = CreateMovementCommandHandler(
        mock_movement_repo,
        event_publisher,
        Mock(),
        FakeAuditTrail(),
        FakeProductQuantities(),
        _stock_repo(),
        inventory_costs(),
    )

    result = handler.handle(command)

    assert result["id"] == 1
    assert result["product_id"] == 1
    assert result["quantity"] == 10
    assert result["type"] == MovementType.IN
    mock_movement_repo.create.assert_called_once()


def test_create_movement_out_command_handler_success(
    mock_movement_repo, event_publisher
):
    """Test creating an OUT movement successfully"""
    command = CreateMovementCommand(
        product_id=1,
        quantity=Decimal(-5),
        type=MovementType.OUT.value,
        reason="Sale #456",
    )

    mock_movement_repo.create.return_value = Movement(
        id=2,
        product_id=1,
        quantity=Decimal(-5),
        type=MovementType.OUT,
        reason="Sale #456",
    )

    handler = CreateMovementCommandHandler(
        mock_movement_repo,
        event_publisher,
        Mock(),
        FakeAuditTrail(),
        FakeProductQuantities(),
        _stock_repo(),
        inventory_costs(),
    )

    result = handler.handle(command)

    assert result["id"] == 2
    assert result["quantity"] == -5
    assert result["type"] == MovementType.OUT
    mock_movement_repo.create.assert_called_once()


def test_create_movement_publishes_movement_created_event(
    mock_movement_repo, event_publisher
):
    """Test that creating a movement publishes MovementCreated event"""
    command = CreateMovementCommand(
        product_id=1,
        quantity=Decimal(10),
        type=MovementType.IN.value,
        reason="Test",
    )

    mock_movement_repo.create.return_value = Movement(
        id=1,
        product_id=1,
        quantity=Decimal(10),
        type=MovementType.IN,
        reason="Test",
        date=datetime.now(),
    )

    handler = CreateMovementCommandHandler(
        mock_movement_repo,
        event_publisher,
        Mock(),
        FakeAuditTrail(),
        FakeProductQuantities(),
        _stock_repo(),
        inventory_costs(),
    )
    handler.handle(command)

    event_publisher.publish.assert_called_once()
    published_event = event_publisher.publish.call_args[0][0]
    assert isinstance(published_event, MovementCreated)
    assert published_event.aggregate_id == 1
    assert published_event.product_id == 1
    assert published_event.quantity == 10
    assert published_event.type == MovementType.IN.value


def test_create_movement_in_with_negative_quantity_raises(
    mock_movement_repo, event_publisher
):
    """Test that IN movement with negative quantity raises exception"""
    command = CreateMovementCommand(
        product_id=1,
        quantity=Decimal(-10),  # Invalid: negative for IN
        type=MovementType.IN.value,
    )

    handler = CreateMovementCommandHandler(
        mock_movement_repo,
        event_publisher,
        Mock(),
        FakeAuditTrail(),
        FakeProductQuantities(),
        _stock_repo(),
        inventory_costs(),
    )

    with pytest.raises(InvalidMovementTypeError) as exc_info:
        handler.handle(command)

    assert exc_info.value.detail is not None
    assert "positiva" in exc_info.value.detail.lower()
    mock_movement_repo.create.assert_not_called()


def test_create_movement_out_with_positive_quantity_raises(
    mock_movement_repo, event_publisher
):
    """Test that OUT movement with positive quantity raises exception"""
    command = CreateMovementCommand(
        product_id=1,
        quantity=Decimal(10),  # Invalid: positive for OUT
        type=MovementType.OUT.value,
    )

    handler = CreateMovementCommandHandler(
        mock_movement_repo,
        event_publisher,
        Mock(),
        FakeAuditTrail(),
        FakeProductQuantities(),
        _stock_repo(),
        inventory_costs(),
    )

    with pytest.raises(InvalidMovementTypeError) as exc_info:
        handler.handle(command)

    assert exc_info.value.detail is not None
    assert "negativa" in exc_info.value.detail.lower()
    mock_movement_repo.create.assert_not_called()


def test_create_movement_zero_quantity_raises(mock_movement_repo, event_publisher):
    """Test that zero quantity raises exception"""
    command = CreateMovementCommand(
        product_id=1,
        quantity=Decimal(0),  # Invalid: zero
        type=MovementType.IN.value,
    )

    handler = CreateMovementCommandHandler(
        mock_movement_repo,
        event_publisher,
        Mock(),
        FakeAuditTrail(),
        FakeProductQuantities(),
        _stock_repo(),
        inventory_costs(),
    )

    with pytest.raises(InvalidMovementTypeError) as exc_info:
        handler.handle(command)

    assert exc_info.value.detail is not None
    assert "cero" in exc_info.value.detail.lower()
    mock_movement_repo.create.assert_not_called()


def test_create_movement_with_date(mock_movement_repo, event_publisher):
    """Test creating movement with specific date"""
    specific_date = datetime(2026, 1, 15, 10, 30)
    command = CreateMovementCommand(
        product_id=1,
        quantity=Decimal(10),
        type=MovementType.IN.value,
        date=specific_date,
    )

    mock_movement_repo.create.return_value = Movement(
        id=1,
        product_id=1,
        quantity=Decimal(10),
        type=MovementType.IN,
        date=specific_date,
    )

    handler = CreateMovementCommandHandler(
        mock_movement_repo,
        event_publisher,
        Mock(),
        FakeAuditTrail(),
        FakeProductQuantities(),
        _stock_repo(),
        inventory_costs(),
    )

    result = handler.handle(command)

    assert result["date"] == specific_date
    mock_movement_repo.create.assert_called_once()


def test_a_manual_movement_takes_the_decimals_of_the_product_unit(
    mock_movement_repo, event_publisher
):
    handler = CreateMovementCommandHandler(
        mock_movement_repo,
        event_publisher,
        Mock(),
        FakeAuditTrail(),
        FakeProductQuantities(decimals={1: 0}),
        _stock_repo(),
        inventory_costs(),
    )

    with pytest.raises(QuantityPrecisionError):
        handler.handle(
            CreateMovementCommand(
                product_id=1,
                quantity=Decimal("1.5"),
                type=MovementType.IN.value,
                manual=True,
            )
        )
    mock_movement_repo.create.assert_not_called()


def test_a_document_movement_is_not_checked_again(mock_movement_repo, event_publisher):
    mock_movement_repo.create.side_effect = lambda m: replace(m, id=1)
    handler = CreateMovementCommandHandler(
        mock_movement_repo,
        event_publisher,
        Mock(),
        FakeAuditTrail(),
        FakeProductQuantities(decimals={1: 0}),
        _stock_repo(),
        inventory_costs(),
    )

    result = handler.handle(
        CreateMovementCommand(
            product_id=1, quantity=Decimal("-2.5"), type=MovementType.OUT.value
        )
    )

    assert result["quantity"] == Decimal("-2.5")


# --- Its cost (S5.6) ---


def _costing_handler(stock=None, audit=None, purchase_prices=None):
    repo = Mock()
    repo.create.side_effect = lambda m: replace(m, id=1)
    stock_repo = _stock_repo(stock)
    publisher = MagicMock()
    handler = CreateMovementCommandHandler(
        repo,
        publisher,
        Mock(),
        audit or FakeAuditTrail(),
        FakeProductQuantities(),
        stock_repo,
        inventory_costs(purchase_prices),
    )
    return handler, stock_repo, publisher


def _row(quantity: str, average_cost: str) -> Stock:
    return Stock(
        id=3,
        product_id=1,
        location_id=7,
        quantity=Decimal(quantity),
        average_cost=Decimal(average_cost),
    )


def test_an_in_carries_its_cost_to_the_stock_handler():
    handler, stock_repo, publisher = _costing_handler(_row("10", "5.00"))

    result = handler.handle(
        CreateMovementCommand(
            product_id=1,
            quantity=Decimal(30),
            type=MovementType.IN.value,
            location_id=7,
            unit_cost=Decimal("7.00"),
        )
    )

    # Locks the row the stock handler updates, before writing the movement
    stock_repo.first_for_update.assert_called_once_with(product_id=1, location_id=7)
    assert result["unit_cost"] == Decimal("7.00")
    event = publisher.publish.call_args.args[0]
    assert isinstance(event, MovementCreated)
    assert event.unit_cost == Decimal("7.00")


def test_an_in_without_cost_enters_at_the_average_of_the_location():
    handler, _, _ = _costing_handler(_row("10", "6.50"))

    result = handler.handle(
        CreateMovementCommand(
            product_id=1, quantity=Decimal(2), type="IN", location_id=7
        )
    )

    assert result["unit_cost"] == Decimal("6.50")


def test_an_in_where_the_product_never_was_takes_its_purchase_price():
    handler, _, _ = _costing_handler(None, purchase_prices={1: Decimal("4.20")})

    result = handler.handle(
        CreateMovementCommand(
            product_id=1, quantity=Decimal(2), type="IN", location_id=7
        )
    )

    assert result["unit_cost"] == Decimal("4.20")


def test_an_out_leaves_at_the_average_of_the_location():
    handler, _, publisher = _costing_handler(_row("40", "6.50"))

    result = handler.handle(
        CreateMovementCommand(
            product_id=1, quantity=Decimal(-15), type="OUT", location_id=7
        )
    )

    assert result["unit_cost"] == Decimal("6.50")
    assert publisher.publish.call_args.args[0].unit_cost == Decimal("6.50")


def test_an_out_takes_no_cost_of_its_own():
    handler, _, _ = _costing_handler(_row("40", "6.50"))

    with pytest.raises(InvalidMovementTypeError):
        handler.handle(
            CreateMovementCommand(
                product_id=1,
                quantity=Decimal(-1),
                type="OUT",
                location_id=7,
                unit_cost=Decimal("1.00"),
            )
        )


def test_the_audit_log_keeps_the_cost_of_a_manual_movement():
    audit = FakeAuditTrail()
    handler, _, _ = _costing_handler(_row("0", "0"), audit=audit)

    handler.handle(
        CreateMovementCommand(
            product_id=1,
            quantity=Decimal(5),
            type="IN",
            location_id=7,
            unit_cost=Decimal("3.10"),
            manual=True,
        )
    )

    (entry,) = audit.entries
    assert entry.after is not None and entry.after["unit_cost"] == Decimal("3.10")
