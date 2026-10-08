"""Unit tests for inventory adjustment command handlers"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.inventory.adjustment.app.commands.adjustment import (
    AddAdjustmentItemCommand,
    AddAdjustmentItemCommandHandler,
    CancelAdjustmentCommand,
    CancelAdjustmentCommandHandler,
    ConfirmAdjustmentCommand,
    ConfirmAdjustmentCommandHandler,
    CreateAdjustmentCommand,
    CreateAdjustmentCommandHandler,
    DeleteAdjustmentCommand,
    DeleteAdjustmentCommandHandler,
    RemoveAdjustmentItemCommand,
    RemoveAdjustmentItemCommandHandler,
    UpdateAdjustmentCommand,
    UpdateAdjustmentCommandHandler,
    UpdateAdjustmentItemCommand,
    UpdateAdjustmentItemCommandHandler,
)
from src.inventory.adjustment.domain.entities import (
    AdjustmentItem,
    AdjustmentReason,
    AdjustmentStatus,
    InventoryAdjustment,
)
from src.shared.domain.exceptions import DomainError, NotFoundError


def _make_adjustment(**overrides) -> InventoryAdjustment:
    defaults: dict[str, Any] = {
        "id": 1,
        "warehouse_id": 10,
        "reason": AdjustmentReason.PHYSICAL_COUNT,
        "status": AdjustmentStatus.DRAFT,
    }
    defaults.update(overrides)
    return InventoryAdjustment(**defaults)


def _make_item(**overrides) -> AdjustmentItem:
    defaults: dict[str, Any] = {
        "id": 1,
        "adjustment_id": 1,
        "product_id": 5,
        "location_id": 3,
        "expected_quantity": 100,
        "actual_quantity": 110,
    }
    defaults.update(overrides)
    return AdjustmentItem(**defaults)


# ---------------------------------------------------------------------------
# CreateAdjustmentCommandHandler
# ---------------------------------------------------------------------------


def test_create_adjustment_success():
    adj = _make_adjustment()
    repo = MagicMock()
    repo.create.return_value = adj
    handler = CreateAdjustmentCommandHandler(repo)

    result = handler.handle(
        CreateAdjustmentCommand(
            warehouse_id=10,
            reason=AdjustmentReason.PHYSICAL_COUNT.value,
        )
    )

    repo.create.assert_called_once()
    assert result["warehouse_id"] == 10
    assert result["status"] == AdjustmentStatus.DRAFT


# ---------------------------------------------------------------------------
# UpdateAdjustmentCommandHandler
# ---------------------------------------------------------------------------


def test_update_adjustment_success():
    adj = _make_adjustment(notes=None)
    updated = _make_adjustment(notes="Updated notes")
    repo = MagicMock()
    repo.get_by_id.return_value = adj
    repo.update.return_value = updated
    handler = UpdateAdjustmentCommandHandler(repo)

    result = handler.handle(UpdateAdjustmentCommand(id=1, notes="Updated notes"))

    repo.update.assert_called_once()
    assert result["notes"] == "Updated notes"


def test_update_adjustment_raises_if_not_draft():
    adj = _make_adjustment(status=AdjustmentStatus.CONFIRMED)
    repo = MagicMock()
    repo.get_by_id.return_value = adj
    handler = UpdateAdjustmentCommandHandler(repo)

    with pytest.raises(DomainError):
        handler.handle(UpdateAdjustmentCommand(id=1, notes="test"))


# ---------------------------------------------------------------------------
# DeleteAdjustmentCommandHandler
# ---------------------------------------------------------------------------


def test_delete_adjustment_success():
    adj = _make_adjustment(status=AdjustmentStatus.DRAFT)
    repo = MagicMock()
    repo.get_by_id.return_value = adj
    handler = DeleteAdjustmentCommandHandler(repo)

    handler.handle(DeleteAdjustmentCommand(id=1))

    repo.delete.assert_called_once_with(1)


def test_delete_adjustment_raises_if_confirmed():
    adj = _make_adjustment(status=AdjustmentStatus.CONFIRMED)
    repo = MagicMock()
    repo.get_by_id.return_value = adj
    handler = DeleteAdjustmentCommandHandler(repo)

    with pytest.raises(DomainError):
        handler.handle(DeleteAdjustmentCommand(id=1))

    repo.delete.assert_not_called()


# ---------------------------------------------------------------------------
# ConfirmAdjustmentCommandHandler
# ---------------------------------------------------------------------------


def test_confirm_adjustment_creates_in_movement_for_positive_diff():
    adj = _make_adjustment(status=AdjustmentStatus.DRAFT)
    confirmed = _make_adjustment(status=AdjustmentStatus.CONFIRMED)
    item = _make_item(expected_quantity=100, actual_quantity=110)  # diff = +10

    repo = MagicMock()
    repo.get_by_id.return_value = adj
    repo.update.return_value = confirmed

    item_repo = MagicMock()
    item_repo.filter_by.return_value = [item]

    movement_handler = MagicMock()
    event_publisher = MagicMock()

    handler = ConfirmAdjustmentCommandHandler(
        repo, item_repo, movement_handler, event_publisher
    )
    result = handler.handle(ConfirmAdjustmentCommand(id=1))

    movement_handler.handle.assert_called_once()
    call_args = movement_handler.handle.call_args[0][0]
    assert call_args.quantity == 10
    assert call_args.type == "IN"
    assert result["status"] == AdjustmentStatus.CONFIRMED


def test_confirm_adjustment_creates_out_movement_for_negative_diff():
    adj = _make_adjustment(status=AdjustmentStatus.DRAFT)
    confirmed = _make_adjustment(status=AdjustmentStatus.CONFIRMED)
    item = _make_item(expected_quantity=100, actual_quantity=85)  # diff = -15

    repo = MagicMock()
    repo.get_by_id.return_value = adj
    repo.update.return_value = confirmed

    item_repo = MagicMock()
    item_repo.filter_by.return_value = [item]

    movement_handler = MagicMock()
    event_publisher = MagicMock()

    handler = ConfirmAdjustmentCommandHandler(
        repo, item_repo, movement_handler, event_publisher
    )
    handler.handle(ConfirmAdjustmentCommand(id=1))

    call_args = movement_handler.handle.call_args[0][0]
    assert call_args.quantity == -15
    assert call_args.type == "OUT"


def test_confirm_adjustment_skips_zero_diff_items():
    adj = _make_adjustment(status=AdjustmentStatus.DRAFT)
    confirmed = _make_adjustment(status=AdjustmentStatus.CONFIRMED)
    item = _make_item(expected_quantity=100, actual_quantity=100)  # diff = 0

    repo = MagicMock()
    repo.get_by_id.return_value = adj
    repo.update.return_value = confirmed

    item_repo = MagicMock()
    item_repo.filter_by.return_value = [item]

    movement_handler = MagicMock()
    event_publisher = MagicMock()

    handler = ConfirmAdjustmentCommandHandler(
        repo, item_repo, movement_handler, event_publisher
    )
    handler.handle(ConfirmAdjustmentCommand(id=1))

    movement_handler.handle.assert_not_called()


def test_confirm_adjustment_raises_if_not_draft():
    adj = _make_adjustment(status=AdjustmentStatus.CONFIRMED)
    repo = MagicMock()
    repo.get_by_id.return_value = adj

    item_repo = MagicMock()
    movement_handler = MagicMock()
    event_publisher = MagicMock()

    handler = ConfirmAdjustmentCommandHandler(
        repo, item_repo, movement_handler, event_publisher
    )

    with pytest.raises(DomainError):
        handler.handle(ConfirmAdjustmentCommand(id=1))


def test_confirm_adjustment_raises_if_not_found():
    repo = MagicMock()
    repo.get_by_id.return_value = None

    item_repo = MagicMock()
    movement_handler = MagicMock()
    event_publisher = MagicMock()

    handler = ConfirmAdjustmentCommandHandler(
        repo, item_repo, movement_handler, event_publisher
    )

    with pytest.raises(NotFoundError):
        handler.handle(ConfirmAdjustmentCommand(id=99))


# ---------------------------------------------------------------------------
# CancelAdjustmentCommandHandler
# ---------------------------------------------------------------------------


def test_cancel_adjustment_success():
    adj = _make_adjustment(status=AdjustmentStatus.DRAFT)
    cancelled = _make_adjustment(status=AdjustmentStatus.CANCELLED)
    repo = MagicMock()
    repo.get_by_id.return_value = adj
    repo.update.return_value = cancelled
    handler = CancelAdjustmentCommandHandler(repo)

    result = handler.handle(CancelAdjustmentCommand(id=1))

    repo.update.assert_called_once()
    assert result["status"] == AdjustmentStatus.CANCELLED


def test_cancel_confirmed_adjustment_raises():
    adj = _make_adjustment(status=AdjustmentStatus.CONFIRMED)
    repo = MagicMock()
    repo.get_by_id.return_value = adj
    handler = CancelAdjustmentCommandHandler(repo)

    with pytest.raises(DomainError):
        handler.handle(CancelAdjustmentCommand(id=1))


# ---------------------------------------------------------------------------
# AddAdjustmentItemCommandHandler
# ---------------------------------------------------------------------------


def test_add_adjustment_item_success_auto_reads_stock():
    adj = _make_adjustment(status=AdjustmentStatus.DRAFT)
    item = _make_item(expected_quantity=50, actual_quantity=60)

    repo = MagicMock()
    repo.get_by_id.return_value = adj

    item_repo = MagicMock()
    item_repo.create.return_value = item

    stock = MagicMock()
    stock.quantity = 50
    stock_repo = MagicMock()
    stock_repo.first.return_value = stock

    handler = AddAdjustmentItemCommandHandler(repo, item_repo, stock_repo)
    result = handler.handle(
        AddAdjustmentItemCommand(
            adjustment_id=1, product_id=5, location_id=3, actual_quantity=60
        )
    )

    item_repo.create.assert_called_once()
    created_item = item_repo.create.call_args[0][0]
    assert created_item.expected_quantity == 50
    assert result["difference"] == 10


def test_add_adjustment_item_uses_zero_expected_if_no_stock():
    adj = _make_adjustment(status=AdjustmentStatus.DRAFT)
    item = _make_item(expected_quantity=0, actual_quantity=30)

    repo = MagicMock()
    repo.get_by_id.return_value = adj

    item_repo = MagicMock()
    item_repo.create.return_value = item

    stock_repo = MagicMock()
    stock_repo.first.return_value = None  # no stock record

    handler = AddAdjustmentItemCommandHandler(repo, item_repo, stock_repo)
    handler.handle(
        AddAdjustmentItemCommand(
            adjustment_id=1, product_id=5, location_id=3, actual_quantity=30
        )
    )

    created_item = item_repo.create.call_args[0][0]
    assert created_item.expected_quantity == 0


def test_add_adjustment_item_raises_if_adjustment_not_draft():
    adj = _make_adjustment(status=AdjustmentStatus.CONFIRMED)
    repo = MagicMock()
    repo.get_by_id.return_value = adj

    item_repo = MagicMock()
    stock_repo = MagicMock()

    handler = AddAdjustmentItemCommandHandler(repo, item_repo, stock_repo)

    with pytest.raises(DomainError):
        handler.handle(
            AddAdjustmentItemCommand(
                adjustment_id=1, product_id=5, location_id=3, actual_quantity=60
            )
        )

    item_repo.create.assert_not_called()


# ---------------------------------------------------------------------------
# UpdateAdjustmentItemCommandHandler
# ---------------------------------------------------------------------------


def test_update_adjustment_item_success():
    item = _make_item(actual_quantity=110)
    updated_item = _make_item(actual_quantity=95)

    item_repo = MagicMock()
    item_repo.get_by_id.return_value = item
    item_repo.update.return_value = updated_item

    handler = UpdateAdjustmentItemCommandHandler(_draft_parent_repo(), item_repo)
    result = handler.handle(UpdateAdjustmentItemCommand(id=1, actual_quantity=95))

    item_repo.update.assert_called_once()
    assert result["actual_quantity"] == 95


def test_update_adjustment_item_not_found_raises():
    item_repo = MagicMock()
    item_repo.get_by_id.return_value = None

    handler = UpdateAdjustmentItemCommandHandler(_draft_parent_repo(), item_repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdateAdjustmentItemCommand(id=99, actual_quantity=50))


# ---------------------------------------------------------------------------
# RemoveAdjustmentItemCommandHandler
# ---------------------------------------------------------------------------


def test_remove_adjustment_item_success():
    item = _make_item()
    item_repo = MagicMock()
    item_repo.get_by_id.return_value = item

    handler = RemoveAdjustmentItemCommandHandler(_draft_parent_repo(), item_repo)
    handler.handle(RemoveAdjustmentItemCommand(id=1))

    item_repo.delete.assert_called_once_with(1)


def _draft_parent_repo():
    repo = MagicMock()
    repo.get_by_id.return_value = _make_adjustment()
    return repo


@pytest.mark.parametrize(
    "status", [AdjustmentStatus.CONFIRMED, AdjustmentStatus.CANCELLED]
)
def test_update_item_requires_draft_parent(status):
    repo = MagicMock()
    repo.get_by_id.return_value = _make_adjustment(status=status)
    item_repo = MagicMock()
    item_repo.get_by_id.return_value = _make_item()

    handler = UpdateAdjustmentItemCommandHandler(repo, item_repo)

    with pytest.raises(DomainError):
        handler.handle(UpdateAdjustmentItemCommand(id=1, actual_quantity=95))
    item_repo.update.assert_not_called()


@pytest.mark.parametrize(
    "status", [AdjustmentStatus.CONFIRMED, AdjustmentStatus.CANCELLED]
)
def test_remove_item_requires_draft_parent(status):
    repo = MagicMock()
    repo.get_by_id.return_value = _make_adjustment(status=status)
    item_repo = MagicMock()
    item_repo.get_by_id.return_value = _make_item()

    handler = RemoveAdjustmentItemCommandHandler(repo, item_repo)

    with pytest.raises(DomainError):
        handler.handle(RemoveAdjustmentItemCommand(id=1))
    item_repo.delete.assert_not_called()
