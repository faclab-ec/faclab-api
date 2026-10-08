"""Unit tests for stock transfer command handlers"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.inventory.stock.domain.entities import Stock
from src.inventory.transfer.app.commands.transfer import (
    AddTransferItemCommand,
    AddTransferItemCommandHandler,
    CancelStockTransferCommand,
    CancelStockTransferCommandHandler,
    ConfirmStockTransferCommand,
    ConfirmStockTransferCommandHandler,
    CreateStockTransferCommand,
    CreateStockTransferCommandHandler,
    DeleteStockTransferCommand,
    DeleteStockTransferCommandHandler,
    ReceiveStockTransferCommand,
    ReceiveStockTransferCommandHandler,
    RemoveTransferItemCommand,
    RemoveTransferItemCommandHandler,
    UpdateStockTransferCommand,
    UpdateStockTransferCommandHandler,
    UpdateTransferItemCommand,
    UpdateTransferItemCommandHandler,
)
from src.inventory.transfer.domain.entities import (
    StockTransfer,
    StockTransferItem,
    TransferStatus,
)
from src.shared.domain.exceptions import DomainError, NotFoundError


def _make_transfer(**overrides) -> StockTransfer:
    defaults: dict[str, Any] = {
        "id": 1,
        "source_location_id": 10,
        "destination_location_id": 20,
        "status": TransferStatus.DRAFT,
    }
    defaults.update(overrides)
    return StockTransfer(**defaults)


def _make_item(**overrides) -> StockTransferItem:
    defaults: dict[str, Any] = {
        "id": 1,
        "transfer_id": 1,
        "product_id": 5,
        "quantity": 10,
    }
    defaults.update(overrides)
    return StockTransferItem(**defaults)


def _make_stock(**overrides) -> Stock:
    defaults: dict[str, Any] = {
        "id": 1,
        "product_id": 5,
        "location_id": 10,
        "quantity": 50,
        "reserved_quantity": 5,
    }
    defaults.update(overrides)
    return Stock(**defaults)


# ---------------------------------------------------------------------------
# CreateStockTransferCommandHandler
# ---------------------------------------------------------------------------


def test_create_transfer_success():
    transfer = _make_transfer()
    repo = MagicMock()
    repo.create.return_value = transfer
    handler = CreateStockTransferCommandHandler(repo)

    result = handler.handle(
        CreateStockTransferCommand(
            source_location_id=10,
            destination_location_id=20,
        )
    )

    repo.create.assert_called_once()
    assert result["source_location_id"] == 10
    assert result["destination_location_id"] == 20
    assert result["status"] == TransferStatus.DRAFT


def test_create_transfer_same_location_raises():
    repo = MagicMock()
    handler = CreateStockTransferCommandHandler(repo)

    with pytest.raises(DomainError):
        handler.handle(
            CreateStockTransferCommand(
                source_location_id=10,
                destination_location_id=10,
            )
        )

    repo.create.assert_not_called()


# ---------------------------------------------------------------------------
# UpdateStockTransferCommandHandler
# ---------------------------------------------------------------------------


def test_update_transfer_success():
    transfer = _make_transfer(notes=None)
    updated = _make_transfer(notes="Updated notes")
    repo = MagicMock()
    repo.get_by_id.return_value = transfer
    repo.update.return_value = updated
    handler = UpdateStockTransferCommandHandler(repo)

    result = handler.handle(UpdateStockTransferCommand(id=1, notes="Updated notes"))

    repo.update.assert_called_once()
    assert result["notes"] == "Updated notes"


def test_update_transfer_raises_if_not_draft():
    transfer = _make_transfer(status=TransferStatus.CONFIRMED)
    repo = MagicMock()
    repo.get_by_id.return_value = transfer
    handler = UpdateStockTransferCommandHandler(repo)

    with pytest.raises(DomainError):
        handler.handle(UpdateStockTransferCommand(id=1, notes="test"))


def test_update_transfer_raises_if_not_found():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = UpdateStockTransferCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdateStockTransferCommand(id=99, notes="test"))


# ---------------------------------------------------------------------------
# DeleteStockTransferCommandHandler
# ---------------------------------------------------------------------------


def test_delete_transfer_success():
    transfer = _make_transfer(status=TransferStatus.DRAFT)
    repo = MagicMock()
    repo.get_by_id.return_value = transfer
    handler = DeleteStockTransferCommandHandler(repo)

    handler.handle(DeleteStockTransferCommand(id=1))

    repo.delete.assert_called_once_with(1)


def test_delete_transfer_raises_if_confirmed():
    transfer = _make_transfer(status=TransferStatus.CONFIRMED)
    repo = MagicMock()
    repo.get_by_id.return_value = transfer
    handler = DeleteStockTransferCommandHandler(repo)

    with pytest.raises(DomainError):
        handler.handle(DeleteStockTransferCommand(id=1))

    repo.delete.assert_not_called()


# ---------------------------------------------------------------------------
# ConfirmStockTransferCommandHandler
# ---------------------------------------------------------------------------


def test_confirm_transfer_reserves_stock():
    transfer = _make_transfer(status=TransferStatus.DRAFT)
    confirmed = _make_transfer(status=TransferStatus.CONFIRMED)
    item = _make_item(product_id=5, quantity=10)
    stock = _make_stock(quantity=50, reserved_quantity=5)  # available = 45

    repo = MagicMock()
    repo.get_by_id.return_value = transfer
    repo.update.return_value = confirmed

    item_repo = MagicMock()
    item_repo.filter_by.return_value = [item]

    stock_repo = MagicMock()
    stock_repo.first.return_value = stock

    event_publisher = MagicMock()

    handler = ConfirmStockTransferCommandHandler(
        repo, item_repo, stock_repo, event_publisher
    )
    result = handler.handle(ConfirmStockTransferCommand(id=1))

    # Stock should be updated with reserved_quantity + item.quantity
    stock_repo.update.assert_called_once()
    updated_stock = stock_repo.update.call_args[0][0]
    assert updated_stock.reserved_quantity == 15  # 5 + 10
    assert result["status"] == TransferStatus.CONFIRMED
    event_publisher.publish.assert_called_once()


def test_confirm_transfer_validates_insufficient_stock():
    transfer = _make_transfer(status=TransferStatus.DRAFT)
    item = _make_item(product_id=5, quantity=10)
    stock = _make_stock(quantity=10, reserved_quantity=5)  # available = 5, need 10

    repo = MagicMock()
    repo.get_by_id.return_value = transfer

    item_repo = MagicMock()
    item_repo.filter_by.return_value = [item]

    stock_repo = MagicMock()
    stock_repo.first.return_value = stock

    event_publisher = MagicMock()

    handler = ConfirmStockTransferCommandHandler(
        repo, item_repo, stock_repo, event_publisher
    )

    with pytest.raises(DomainError):
        handler.handle(ConfirmStockTransferCommand(id=1))

    stock_repo.update.assert_not_called()
    repo.update.assert_not_called()
    event_publisher.publish.assert_not_called()


def test_confirm_transfer_validates_no_stock_record():
    transfer = _make_transfer(status=TransferStatus.DRAFT)
    item = _make_item(product_id=5, quantity=5)

    repo = MagicMock()
    repo.get_by_id.return_value = transfer

    item_repo = MagicMock()
    item_repo.filter_by.return_value = [item]

    stock_repo = MagicMock()
    stock_repo.first.return_value = None  # no stock at all

    event_publisher = MagicMock()

    handler = ConfirmStockTransferCommandHandler(
        repo, item_repo, stock_repo, event_publisher
    )

    with pytest.raises(DomainError):
        handler.handle(ConfirmStockTransferCommand(id=1))


def test_confirm_transfer_raises_if_no_items():
    transfer = _make_transfer(status=TransferStatus.DRAFT)

    repo = MagicMock()
    repo.get_by_id.return_value = transfer

    item_repo = MagicMock()
    item_repo.filter_by.return_value = []

    stock_repo = MagicMock()
    event_publisher = MagicMock()

    handler = ConfirmStockTransferCommandHandler(
        repo, item_repo, stock_repo, event_publisher
    )

    with pytest.raises(DomainError):
        handler.handle(ConfirmStockTransferCommand(id=1))


def test_confirm_transfer_raises_if_not_found():
    repo = MagicMock()
    repo.get_by_id.return_value = None

    item_repo = MagicMock()
    stock_repo = MagicMock()
    event_publisher = MagicMock()

    handler = ConfirmStockTransferCommandHandler(
        repo, item_repo, stock_repo, event_publisher
    )

    with pytest.raises(NotFoundError):
        handler.handle(ConfirmStockTransferCommand(id=99))


# ---------------------------------------------------------------------------
# ReceiveStockTransferCommandHandler
# ---------------------------------------------------------------------------


def test_receive_transfer_creates_movements_and_releases_reservation():
    transfer = _make_transfer(status=TransferStatus.CONFIRMED)
    received = _make_transfer(status=TransferStatus.RECEIVED)
    item = _make_item(product_id=5, quantity=10)
    stock = _make_stock(quantity=50, reserved_quantity=10)

    repo = MagicMock()
    repo.get_by_id.return_value = transfer
    repo.update.return_value = received

    item_repo = MagicMock()
    item_repo.filter_by.return_value = [item]

    stock_repo = MagicMock()
    stock_repo.first.return_value = stock

    movement_handler = MagicMock()
    event_publisher = MagicMock()

    handler = ReceiveStockTransferCommandHandler(
        repo, item_repo, stock_repo, movement_handler, event_publisher
    )
    result = handler.handle(ReceiveStockTransferCommand(id=1))

    # Reservation released
    stock_repo.update.assert_called_once()
    updated_stock = stock_repo.update.call_args[0][0]
    assert updated_stock.reserved_quantity == 0  # 10 - 10

    # Two movements created: OUT from source, IN to destination
    assert movement_handler.handle.call_count == 2
    out_call = movement_handler.handle.call_args_list[0][0][0]
    in_call = movement_handler.handle.call_args_list[1][0][0]
    assert out_call.type == "OUT"
    assert out_call.location_id == 10  # source
    assert in_call.type == "IN"
    assert in_call.location_id == 20  # destination
    assert in_call.source_location_id == 10

    assert result["status"] == TransferStatus.RECEIVED
    event_publisher.publish.assert_called_once()


def test_receive_transfer_raises_if_not_confirmed():
    transfer = _make_transfer(status=TransferStatus.DRAFT)
    repo = MagicMock()
    repo.get_by_id.return_value = transfer

    item_repo = MagicMock()
    stock_repo = MagicMock()
    movement_handler = MagicMock()
    event_publisher = MagicMock()

    handler = ReceiveStockTransferCommandHandler(
        repo, item_repo, stock_repo, movement_handler, event_publisher
    )

    with pytest.raises(DomainError):
        handler.handle(ReceiveStockTransferCommand(id=1))

    movement_handler.handle.assert_not_called()


def test_receive_transfer_raises_if_not_found():
    repo = MagicMock()
    repo.get_by_id.return_value = None

    item_repo = MagicMock()
    stock_repo = MagicMock()
    movement_handler = MagicMock()
    event_publisher = MagicMock()

    handler = ReceiveStockTransferCommandHandler(
        repo, item_repo, stock_repo, movement_handler, event_publisher
    )

    with pytest.raises(NotFoundError):
        handler.handle(ReceiveStockTransferCommand(id=99))


# ---------------------------------------------------------------------------
# CancelStockTransferCommandHandler
# ---------------------------------------------------------------------------


def test_cancel_draft_transfer_does_not_release_reservations():
    transfer = _make_transfer(status=TransferStatus.DRAFT)
    cancelled = _make_transfer(status=TransferStatus.CANCELLED)

    repo = MagicMock()
    repo.get_by_id.return_value = transfer
    repo.update.return_value = cancelled

    item_repo = MagicMock()
    stock_repo = MagicMock()
    event_publisher = MagicMock()

    handler = CancelStockTransferCommandHandler(
        repo, item_repo, stock_repo, event_publisher
    )
    result = handler.handle(CancelStockTransferCommand(id=1))

    item_repo.filter_by.assert_not_called()
    stock_repo.update.assert_not_called()
    assert result["status"] == TransferStatus.CANCELLED
    event_publisher.publish.assert_called_once()


def test_cancel_confirmed_transfer_releases_reservations():
    transfer = _make_transfer(status=TransferStatus.CONFIRMED)
    cancelled = _make_transfer(status=TransferStatus.CANCELLED)
    item = _make_item(product_id=5, quantity=10)
    stock = _make_stock(quantity=50, reserved_quantity=10)

    repo = MagicMock()
    repo.get_by_id.return_value = transfer
    repo.update.return_value = cancelled

    item_repo = MagicMock()
    item_repo.filter_by.return_value = [item]

    stock_repo = MagicMock()
    stock_repo.first.return_value = stock

    event_publisher = MagicMock()

    handler = CancelStockTransferCommandHandler(
        repo, item_repo, stock_repo, event_publisher
    )
    result = handler.handle(CancelStockTransferCommand(id=1))

    stock_repo.update.assert_called_once()
    updated_stock = stock_repo.update.call_args[0][0]
    assert updated_stock.reserved_quantity == 0  # 10 - 10
    assert result["status"] == TransferStatus.CANCELLED


def test_cancel_received_transfer_raises():
    transfer = _make_transfer(status=TransferStatus.RECEIVED)
    repo = MagicMock()
    repo.get_by_id.return_value = transfer

    item_repo = MagicMock()
    stock_repo = MagicMock()
    event_publisher = MagicMock()

    handler = CancelStockTransferCommandHandler(
        repo, item_repo, stock_repo, event_publisher
    )

    with pytest.raises(DomainError):
        handler.handle(CancelStockTransferCommand(id=1))


# ---------------------------------------------------------------------------
# AddTransferItemCommandHandler
# ---------------------------------------------------------------------------


def test_add_transfer_item_success():
    transfer = _make_transfer(status=TransferStatus.DRAFT)
    item = _make_item(product_id=5, quantity=10)

    repo = MagicMock()
    repo.get_by_id.return_value = transfer

    item_repo = MagicMock()
    item_repo.create.return_value = item

    handler = AddTransferItemCommandHandler(repo, item_repo)
    result = handler.handle(
        AddTransferItemCommand(transfer_id=1, product_id=5, quantity=10)
    )

    item_repo.create.assert_called_once()
    assert result["quantity"] == 10


def test_add_transfer_item_raises_if_not_draft():
    transfer = _make_transfer(status=TransferStatus.CONFIRMED)
    repo = MagicMock()
    repo.get_by_id.return_value = transfer

    item_repo = MagicMock()

    handler = AddTransferItemCommandHandler(repo, item_repo)

    with pytest.raises(DomainError):
        handler.handle(AddTransferItemCommand(transfer_id=1, product_id=5, quantity=10))

    item_repo.create.assert_not_called()


def test_add_transfer_item_raises_if_zero_quantity():
    transfer = _make_transfer(status=TransferStatus.DRAFT)
    repo = MagicMock()
    repo.get_by_id.return_value = transfer

    item_repo = MagicMock()

    handler = AddTransferItemCommandHandler(repo, item_repo)

    with pytest.raises(DomainError):
        handler.handle(AddTransferItemCommand(transfer_id=1, product_id=5, quantity=0))


def test_add_transfer_item_raises_if_transfer_not_found():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    item_repo = MagicMock()

    handler = AddTransferItemCommandHandler(repo, item_repo)

    with pytest.raises(NotFoundError):
        handler.handle(
            AddTransferItemCommand(transfer_id=99, product_id=5, quantity=10)
        )


# ---------------------------------------------------------------------------
# UpdateTransferItemCommandHandler
# ---------------------------------------------------------------------------


def test_update_transfer_item_success():
    item = _make_item(quantity=10)
    updated_item = _make_item(quantity=20)

    item_repo = MagicMock()
    item_repo.get_by_id.return_value = item
    item_repo.update.return_value = updated_item

    handler = UpdateTransferItemCommandHandler(_draft_parent_repo(), item_repo)
    result = handler.handle(UpdateTransferItemCommand(id=1, quantity=20))

    item_repo.update.assert_called_once()
    assert result["quantity"] == 20


def test_update_transfer_item_not_found_raises():
    item_repo = MagicMock()
    item_repo.get_by_id.return_value = None

    handler = UpdateTransferItemCommandHandler(_draft_parent_repo(), item_repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdateTransferItemCommand(id=99, quantity=5))


def test_update_transfer_item_zero_quantity_raises():
    item = _make_item(quantity=10)
    item_repo = MagicMock()
    item_repo.get_by_id.return_value = item

    handler = UpdateTransferItemCommandHandler(_draft_parent_repo(), item_repo)

    with pytest.raises(DomainError):
        handler.handle(UpdateTransferItemCommand(id=1, quantity=0))


# ---------------------------------------------------------------------------
# RemoveTransferItemCommandHandler
# ---------------------------------------------------------------------------


def test_remove_transfer_item_success():
    item = _make_item()
    item_repo = MagicMock()
    item_repo.get_by_id.return_value = item

    handler = RemoveTransferItemCommandHandler(_draft_parent_repo(), item_repo)
    handler.handle(RemoveTransferItemCommand(id=1))

    item_repo.delete.assert_called_once_with(1)


def test_remove_transfer_item_not_found_raises():
    item_repo = MagicMock()
    item_repo.get_by_id.return_value = None

    handler = RemoveTransferItemCommandHandler(_draft_parent_repo(), item_repo)

    with pytest.raises(NotFoundError):
        handler.handle(RemoveTransferItemCommand(id=99))


def _draft_parent_repo():
    repo = MagicMock()
    repo.get_by_id.return_value = _make_transfer()
    return repo


@pytest.mark.parametrize("status", [TransferStatus.CONFIRMED, TransferStatus.CANCELLED])
def test_update_item_requires_draft_parent(status):
    repo = MagicMock()
    repo.get_by_id.return_value = _make_transfer(status=status)
    item_repo = MagicMock()
    item_repo.get_by_id.return_value = _make_item()

    handler = UpdateTransferItemCommandHandler(repo, item_repo)

    with pytest.raises(DomainError):
        handler.handle(UpdateTransferItemCommand(id=1, quantity=20))
    item_repo.update.assert_not_called()


@pytest.mark.parametrize("status", [TransferStatus.CONFIRMED, TransferStatus.CANCELLED])
def test_remove_item_requires_draft_parent(status):
    repo = MagicMock()
    repo.get_by_id.return_value = _make_transfer(status=status)
    item_repo = MagicMock()
    item_repo.get_by_id.return_value = _make_item()

    handler = RemoveTransferItemCommandHandler(repo, item_repo)

    with pytest.raises(DomainError):
        handler.handle(RemoveTransferItemCommand(id=1))
    item_repo.delete.assert_not_called()
