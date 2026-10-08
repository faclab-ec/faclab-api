from typing import Any
from unittest.mock import MagicMock, Mock, patch

from src.inventory.lot.domain.entities import Lot, MovementLotItem
from src.purchasing.domain.events import PurchaseOrderReceived


def _make_event(**overrides) -> PurchaseOrderReceived:
    defaults: dict[str, Any] = {
        "aggregate_id": 1,
        "purchase_order_id": 1,
        "order_number": "PO-2026-0001",
        "is_complete": True,
        "items": [],
    }
    defaults.update(overrides)
    return PurchaseOrderReceived(**defaults)


def _make_lot(**overrides) -> Lot:
    defaults: dict[str, Any] = {
        "id": 1,
        "product_id": 5,
        "lot_number": "LOT-001",
        "initial_quantity": 100,
        "current_quantity": 100,
    }
    defaults.update(overrides)
    return Lot(**defaults)


def _make_scope(lot_repo, movement_lot_item_repo, movement_repo):
    from src.inventory.lot.app.repositories import (
        LotRepository,
        MovementLotItemRepository,
    )
    from src.inventory.movement.app.repositories import MovementRepository

    mock_scope = Mock()

    def _get(cls):
        if cls is LotRepository:
            return lot_repo
        if cls is MovementLotItemRepository:
            return movement_lot_item_repo
        if cls is MovementRepository:
            return movement_repo
        return MagicMock()

    mock_scope.get.side_effect = _get
    return mock_scope


# ---------------------------------------------------------------------------
# handle_purchase_order_received_lots
# ---------------------------------------------------------------------------


@patch("src.inventory.lot.infra.event_handlers.create_sync_scope")
def test_skips_items_without_lot_number(mock_create_scope):
    """Items without lot_number should not trigger lot creation."""
    event = _make_event(
        items=[
            {
                "product_id": 5,
                "quantity": 10,
                "location_id": None,
                "lot_number": None,
                "serial_numbers": [],
            }
        ]
    )

    from src.inventory.lot.infra.event_handlers import (
        handle_purchase_order_received_lots,
    )

    handle_purchase_order_received_lots(event)

    mock_create_scope.assert_not_called()


@patch("src.inventory.lot.infra.event_handlers.create_sync_scope")
def test_creates_new_lot_when_not_exists(mock_create_scope):
    """Creates a new lot when lot_number is provided and doesn't exist."""
    lot = _make_lot()
    event = _make_event(
        items=[
            {
                "product_id": 5,
                "quantity": 10,
                "location_id": None,
                "lot_number": "LOT-001",
                "serial_numbers": [],
            }
        ]
    )

    lot_repo = MagicMock()
    lot_repo.first.return_value = None
    lot_repo.create.return_value = lot

    movement_lot_item_repo = MagicMock()
    movement_repo = MagicMock()
    movement_repo.filter_by.return_value = []

    mock_scope = _make_scope(lot_repo, movement_lot_item_repo, movement_repo)
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    from src.inventory.lot.infra.event_handlers import (
        handle_purchase_order_received_lots,
    )

    handle_purchase_order_received_lots(event)

    lot_repo.first.assert_called_once_with(product_id=5, lot_number="LOT-001")
    lot_repo.create.assert_called_once()
    created = lot_repo.create.call_args[0][0]
    assert created.product_id == 5
    assert created.lot_number == "LOT-001"
    assert created.initial_quantity == 10
    assert created.current_quantity == 10


@patch("src.inventory.lot.infra.event_handlers.create_sync_scope")
def test_updates_existing_lot_quantity(mock_create_scope):
    """Updates current_quantity when lot already exists."""
    existing_lot = _make_lot(current_quantity=50)
    updated_lot = _make_lot(current_quantity=60)
    event = _make_event(
        items=[
            {
                "product_id": 5,
                "quantity": 10,
                "location_id": None,
                "lot_number": "LOT-001",
                "serial_numbers": [],
            }
        ]
    )

    lot_repo = MagicMock()
    lot_repo.first.return_value = existing_lot
    lot_repo.update.return_value = updated_lot

    movement_lot_item_repo = MagicMock()
    movement_repo = MagicMock()
    movement_repo.filter_by.return_value = []

    mock_scope = _make_scope(lot_repo, movement_lot_item_repo, movement_repo)
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    from src.inventory.lot.infra.event_handlers import (
        handle_purchase_order_received_lots,
    )

    handle_purchase_order_received_lots(event)

    lot_repo.update.assert_called_once()
    updated = lot_repo.update.call_args[0][0]
    assert updated.initial_quantity == 110  # 100 + 10
    assert updated.current_quantity == 60  # 50 + 10


@patch("src.inventory.lot.infra.event_handlers.create_sync_scope")
def test_creates_movement_lot_item_when_movement_exists(mock_create_scope):
    """Creates MovementLotItem linking movement to lot."""
    from src.inventory.movement.domain.constants import MovementType
    from src.inventory.movement.domain.entities import Movement

    lot = _make_lot()
    movement = Movement(
        id=10,
        product_id=5,
        quantity=10,
        type=MovementType.IN,
        reference_type="purchase_order",
        reference_id=1,
    )
    event = _make_event(
        items=[
            {
                "product_id": 5,
                "quantity": 10,
                "location_id": None,
                "lot_number": "LOT-001",
                "serial_numbers": [],
            }
        ]
    )

    lot_repo = MagicMock()
    lot_repo.first.return_value = None
    lot_repo.create.return_value = lot

    movement_lot_item_repo = MagicMock()
    movement_lot_item_repo.create.return_value = MovementLotItem(
        id=1, movement_id=10, lot_id=1, quantity=10
    )

    movement_repo = MagicMock()
    movement_repo.filter_by.return_value = [movement]

    mock_scope = _make_scope(lot_repo, movement_lot_item_repo, movement_repo)
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    from src.inventory.lot.infra.event_handlers import (
        handle_purchase_order_received_lots,
    )

    handle_purchase_order_received_lots(event)

    movement_repo.filter_by.assert_called_once_with(
        reference_type="purchase_order",
        reference_id=1,
        product_id=5,
        quantity=10,
    )
    movement_lot_item_repo.create.assert_called_once()
    created = movement_lot_item_repo.create.call_args[0][0]
    assert created.movement_id == 10
    assert created.lot_id == 1
    assert created.quantity == 10


@patch("src.inventory.lot.infra.event_handlers.create_sync_scope")
def test_does_not_reuse_movement_for_duplicate_product_items(mock_create_scope):
    """Each item gets its own movement even with same product_id."""
    from src.inventory.movement.domain.constants import MovementType
    from src.inventory.movement.domain.entities import Movement

    lot1 = _make_lot(id=1)
    lot2 = _make_lot(id=2, lot_number="LOT-002")
    movement1 = Movement(
        id=10,
        product_id=5,
        quantity=10,
        type=MovementType.IN,
        reference_type="purchase_order",
        reference_id=1,
    )
    movement2 = Movement(
        id=11,
        product_id=5,
        quantity=10,
        type=MovementType.IN,
        reference_type="purchase_order",
        reference_id=1,
    )
    event = _make_event(
        items=[
            {
                "product_id": 5,
                "quantity": 10,
                "location_id": None,
                "lot_number": "LOT-001",
                "serial_numbers": [],
            },
            {
                "product_id": 5,
                "quantity": 10,
                "location_id": None,
                "lot_number": "LOT-002",
                "serial_numbers": [],
            },
        ]
    )

    lot_repo = MagicMock()
    lot_repo.first.side_effect = [None, None]
    lot_repo.create.side_effect = [lot1, lot2]

    movement_lot_item_repo = MagicMock()
    movement_lot_item_repo.create.return_value = MovementLotItem(
        id=1, movement_id=10, lot_id=1, quantity=10
    )

    movement_repo = MagicMock()
    movement_repo.filter_by.return_value = [movement1, movement2]

    mock_scope = _make_scope(lot_repo, movement_lot_item_repo, movement_repo)
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    from src.inventory.lot.infra.event_handlers import (
        handle_purchase_order_received_lots,
    )

    handle_purchase_order_received_lots(event)

    assert movement_lot_item_repo.create.call_count == 2
    first_call = movement_lot_item_repo.create.call_args_list[0][0][0]
    second_call = movement_lot_item_repo.create.call_args_list[1][0][0]
    assert first_call.movement_id == 10
    assert second_call.movement_id == 11
