"""Unit tests for StockTransfer and StockTransferItem entities"""

from typing import Any

import pytest

from src.inventory.transfer.domain.entities import (
    StockTransfer,
    StockTransferItem,
    TransferStatus,
)
from src.inventory.transfer.domain.exceptions import (
    InvalidTransferStatusError,
    SameLocationTransferError,
)
from src.shared.domain.exceptions import ValidationError


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


# ---------------------------------------------------------------------------
# StockTransfer.confirm()
# ---------------------------------------------------------------------------


def test_confirm_draft_transfer():
    transfer = _make_transfer(status=TransferStatus.DRAFT)
    transfer.confirm()
    assert transfer.status == TransferStatus.CONFIRMED


def test_confirm_confirmed_transfer_raises():
    transfer = _make_transfer(status=TransferStatus.CONFIRMED)
    with pytest.raises(InvalidTransferStatusError):
        transfer.confirm()


def test_confirm_cancelled_transfer_raises():
    transfer = _make_transfer(status=TransferStatus.CANCELLED)
    with pytest.raises(InvalidTransferStatusError):
        transfer.confirm()


def test_confirm_received_transfer_raises():
    transfer = _make_transfer(status=TransferStatus.RECEIVED)
    with pytest.raises(InvalidTransferStatusError):
        transfer.confirm()


# ---------------------------------------------------------------------------
# StockTransfer.receive()
# ---------------------------------------------------------------------------


def test_receive_confirmed_transfer():
    transfer = _make_transfer(status=TransferStatus.CONFIRMED)
    transfer.receive()
    assert transfer.status == TransferStatus.RECEIVED


def test_receive_draft_transfer_raises():
    transfer = _make_transfer(status=TransferStatus.DRAFT)
    with pytest.raises(InvalidTransferStatusError):
        transfer.receive()


def test_receive_received_transfer_raises():
    transfer = _make_transfer(status=TransferStatus.RECEIVED)
    with pytest.raises(InvalidTransferStatusError):
        transfer.receive()


# ---------------------------------------------------------------------------
# StockTransfer.cancel()
# ---------------------------------------------------------------------------


def test_cancel_draft_transfer():
    transfer = _make_transfer(status=TransferStatus.DRAFT)
    transfer.cancel()
    assert transfer.status == TransferStatus.CANCELLED


def test_cancel_confirmed_transfer():
    transfer = _make_transfer(status=TransferStatus.CONFIRMED)
    transfer.cancel()
    assert transfer.status == TransferStatus.CANCELLED


def test_cancel_received_transfer_raises():
    transfer = _make_transfer(status=TransferStatus.RECEIVED)
    with pytest.raises(InvalidTransferStatusError):
        transfer.cancel()


def test_transfer_between_the_same_location_is_rejected():
    with pytest.raises(SameLocationTransferError):
        _make_transfer(source_location_id=10, destination_location_id=10)


def test_update_details_only_in_draft():
    transfer = _make_transfer(notes="old", requested_by="ana")
    transfer.update_details(notes="new")
    assert (transfer.notes, transfer.requested_by) == ("new", "ana")

    transfer.confirm()
    with pytest.raises(InvalidTransferStatusError):
        transfer.update_details(notes="again")


# ---------------------------------------------------------------------------
# StockTransferItem
# ---------------------------------------------------------------------------


def test_transfer_item_quantity_is_positive():
    item = _make_item(quantity=15)
    assert item.quantity == 15


def test_transfer_item_dict_includes_all_fields():
    item = _make_item(quantity=5, lot_id=3, notes="Test")
    d = item.dict()
    assert d["quantity"] == 5
    assert d["lot_id"] == 3
    assert d["notes"] == "Test"


@pytest.mark.parametrize("quantity", [0, -1])
def test_transfer_item_quantity_must_be_positive(quantity):
    with pytest.raises(ValidationError):
        _make_item(quantity=quantity)

    item = _make_item(quantity=5)
    with pytest.raises(ValidationError):
        item.update(quantity=quantity)
    assert item.quantity == 5
