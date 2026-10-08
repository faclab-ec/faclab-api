"""Unit tests for TransfersByStatus and TransfersBySourceLocation specifications"""

from typing import Any

from src.inventory.transfer.domain.entities import StockTransfer, TransferStatus
from src.inventory.transfer.domain.specifications import (
    TransfersBySourceLocation,
    TransfersByStatus,
)


def _make_transfer(**overrides) -> StockTransfer:
    defaults: dict[str, Any] = {
        "id": 1,
        "source_location_id": 10,
        "destination_location_id": 20,
        "status": TransferStatus.DRAFT,
    }
    defaults.update(overrides)
    return StockTransfer(**defaults)


# ---------------------------------------------------------------------------
# TransfersByStatus
# ---------------------------------------------------------------------------


def test_transfers_by_status_matches():
    transfer = _make_transfer(status=TransferStatus.DRAFT)
    spec = TransfersByStatus(TransferStatus.DRAFT)
    assert spec.is_satisfied_by(transfer) is True


def test_transfers_by_status_not_matches():
    transfer = _make_transfer(status=TransferStatus.CONFIRMED)
    spec = TransfersByStatus(TransferStatus.DRAFT)
    assert spec.is_satisfied_by(transfer) is False


def test_transfers_by_status_to_query_criteria():
    spec = TransfersByStatus(TransferStatus.CONFIRMED)
    criteria = spec.to_query_criteria()
    assert len(criteria) == 1


def test_transfers_by_status_received():
    transfer = _make_transfer(status=TransferStatus.RECEIVED)
    spec = TransfersByStatus(TransferStatus.RECEIVED)
    assert spec.is_satisfied_by(transfer) is True


# ---------------------------------------------------------------------------
# TransfersBySourceLocation
# ---------------------------------------------------------------------------


def test_transfers_by_source_location_matches():
    transfer = _make_transfer(source_location_id=10)
    spec = TransfersBySourceLocation(location_id=10)
    assert spec.is_satisfied_by(transfer) is True


def test_transfers_by_source_location_not_matches():
    transfer = _make_transfer(source_location_id=10)
    spec = TransfersBySourceLocation(location_id=99)
    assert spec.is_satisfied_by(transfer) is False


def test_transfers_by_source_location_to_query_criteria():
    spec = TransfersBySourceLocation(location_id=10)
    criteria = spec.to_query_criteria()
    assert len(criteria) == 1


def test_transfers_by_source_location_combined_with_status():
    transfer = _make_transfer(source_location_id=10, status=TransferStatus.CONFIRMED)
    spec = TransfersBySourceLocation(10) & TransfersByStatus(TransferStatus.CONFIRMED)
    assert spec.is_satisfied_by(transfer) is True


def test_transfers_by_source_location_combined_with_status_fails():
    transfer = _make_transfer(source_location_id=10, status=TransferStatus.DRAFT)
    spec = TransfersBySourceLocation(10) & TransfersByStatus(TransferStatus.CONFIRMED)
    assert spec.is_satisfied_by(transfer) is False
