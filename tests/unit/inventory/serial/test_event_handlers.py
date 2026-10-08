from typing import Any
from unittest.mock import MagicMock, Mock, patch

from src.inventory.lot.domain.entities import Lot
from src.inventory.serial.domain.entities import SerialNumber, SerialStatus
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


def _make_scope(serial_repo, lot_repo):
    from src.inventory.lot.app.repositories import LotRepository
    from src.inventory.serial.app.repositories import SerialNumberRepository

    mock_scope = Mock()

    def _get(cls):
        if cls is SerialNumberRepository:
            return serial_repo
        if cls is LotRepository:
            return lot_repo
        return MagicMock()

    mock_scope.get.side_effect = _get
    return mock_scope


# ---------------------------------------------------------------------------
# handle_purchase_order_received_serials
# ---------------------------------------------------------------------------


@patch("src.inventory.serial.infra.event_handlers.create_sync_scope")
def test_skips_items_without_serial_numbers(mock_create_scope):
    """Items without serial_numbers should not trigger serial creation."""
    from src.inventory.serial.infra import event_handlers  # noqa: F401

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

    from src.inventory.serial.infra.event_handlers import (
        handle_purchase_order_received_serials,
    )

    handle_purchase_order_received_serials(event)

    mock_create_scope.assert_not_called()


@patch("src.inventory.serial.infra.event_handlers.create_sync_scope")
def test_creates_serial_numbers_when_provided(mock_create_scope):
    """Creates serial numbers for items with serial_numbers list."""
    from src.inventory.serial.infra import event_handlers  # noqa: F401

    serial = SerialNumber(
        id=1, product_id=5, serial_number="SN-001", status=SerialStatus.AVAILABLE
    )
    event = _make_event(
        items=[
            {
                "product_id": 5,
                "quantity": 1,
                "location_id": None,
                "lot_number": None,
                "serial_numbers": ["SN-001"],
                "purchase_order_id": 1,
            }
        ]
    )

    serial_repo = MagicMock()
    serial_repo.first.return_value = None
    serial_repo.create.return_value = serial

    lot_repo = MagicMock()
    lot_repo.first.return_value = None

    mock_scope = _make_scope(serial_repo, lot_repo)
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    from src.inventory.serial.infra.event_handlers import (
        handle_purchase_order_received_serials,
    )

    handle_purchase_order_received_serials(event)

    serial_repo.first.assert_called_once_with(serial_number="SN-001")
    serial_repo.create.assert_called_once()
    created = serial_repo.create.call_args[0][0]
    assert created.product_id == 5
    assert created.serial_number == "SN-001"
    assert created.status == SerialStatus.AVAILABLE
    assert created.lot_id is None


@patch("src.inventory.serial.infra.event_handlers.create_sync_scope")
def test_associates_lot_id_when_lot_number_provided(mock_create_scope):
    """Associates lot_id when lot_number is present in the item."""
    from src.inventory.serial.infra import event_handlers  # noqa: F401

    lot = Lot(
        id=3,
        product_id=5,
        lot_number="LOT-001",
        initial_quantity=10,
        current_quantity=10,
    )
    serial = SerialNumber(
        id=1,
        product_id=5,
        serial_number="SN-001",
        status=SerialStatus.AVAILABLE,
        lot_id=3,
    )

    event = _make_event(
        items=[
            {
                "product_id": 5,
                "quantity": 1,
                "location_id": None,
                "lot_number": "LOT-001",
                "serial_numbers": ["SN-001"],
                "purchase_order_id": 1,
            }
        ]
    )

    serial_repo = MagicMock()
    serial_repo.first.return_value = None
    serial_repo.create.return_value = serial

    lot_repo = MagicMock()
    lot_repo.first.return_value = lot

    mock_scope = _make_scope(serial_repo, lot_repo)
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    from src.inventory.serial.infra.event_handlers import (
        handle_purchase_order_received_serials,
    )

    handle_purchase_order_received_serials(event)

    created = serial_repo.create.call_args[0][0]
    assert created.lot_id == 3


@patch("src.inventory.serial.infra.event_handlers.create_sync_scope")
def test_skips_duplicate_serial_numbers(mock_create_scope):
    """Does not create a serial that already exists."""
    from src.inventory.serial.infra import event_handlers  # noqa: F401

    existing_serial = SerialNumber(
        id=1, product_id=5, serial_number="SN-DUP", status=SerialStatus.AVAILABLE
    )
    event = _make_event(
        items=[
            {
                "product_id": 5,
                "quantity": 1,
                "location_id": None,
                "lot_number": None,
                "serial_numbers": ["SN-DUP"],
                "purchase_order_id": 1,
            }
        ]
    )

    serial_repo = MagicMock()
    serial_repo.first.return_value = existing_serial

    lot_repo = MagicMock()
    lot_repo.first.return_value = None

    mock_scope = _make_scope(serial_repo, lot_repo)
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    from src.inventory.serial.infra.event_handlers import (
        handle_purchase_order_received_serials,
    )

    handle_purchase_order_received_serials(event)

    serial_repo.create.assert_not_called()


@patch("src.inventory.serial.infra.event_handlers.create_sync_scope")
def test_logs_error_when_serial_exists_for_different_product(mock_create_scope):
    """Logs error when serial already exists for a different product."""
    from src.inventory.serial.infra import event_handlers  # noqa: F401

    existing_serial = SerialNumber(
        id=1, product_id=99, serial_number="SN-MISMATCH", status=SerialStatus.AVAILABLE
    )
    event = _make_event(
        items=[
            {
                "product_id": 5,
                "quantity": 1,
                "location_id": None,
                "lot_number": None,
                "serial_numbers": ["SN-MISMATCH"],
                "purchase_order_id": 1,
            }
        ]
    )

    serial_repo = MagicMock()
    serial_repo.first.return_value = existing_serial

    lot_repo = MagicMock()
    lot_repo.first.return_value = None

    mock_scope = _make_scope(serial_repo, lot_repo)
    mock_create_scope.return_value.__enter__.return_value = mock_scope

    from src.inventory.serial.infra.event_handlers import (
        handle_purchase_order_received_serials,
    )

    handle_purchase_order_received_serials(event)

    serial_repo.create.assert_not_called()
