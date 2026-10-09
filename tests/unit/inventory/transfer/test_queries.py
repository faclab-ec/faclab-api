"""Unit tests for stock transfer query handlers"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.inventory.transfer.app.queries.transfer import (
    GetAllTransfersQuery,
    GetAllTransfersQueryHandler,
    GetTransferByIdQuery,
    GetTransferByIdQueryHandler,
    GetTransferItemsQuery,
    GetTransferItemsQueryHandler,
)
from src.inventory.transfer.domain.entities import (
    StockTransfer,
    StockTransferItem,
    TransferStatus,
)
from src.shared.domain.exceptions import NotFoundError


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
# GetAllTransfersQueryHandler
# ---------------------------------------------------------------------------


def test_get_all_transfers_no_filters():
    t1 = _make_transfer(id=1)
    t2 = _make_transfer(id=2, status=TransferStatus.CONFIRMED)

    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [t1.dict(), t2.dict()],
    }
    handler = GetAllTransfersQueryHandler(repo)

    result = handler.handle(GetAllTransfersQuery())

    repo.paginate.assert_called_once()
    assert len(result["items"]) == 2
    assert result["total"] == 2


def test_get_all_transfers_filtered_by_status():
    t = _make_transfer(id=1, status=TransferStatus.CONFIRMED)

    repo = MagicMock()
    repo.paginate_by_spec.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [t.dict()],
    }
    handler = GetAllTransfersQueryHandler(repo)

    result = handler.handle(GetAllTransfersQuery(status="confirmed"))

    repo.paginate_by_spec.assert_called_once()
    assert len(result["items"]) == 1
    assert result["items"][0]["status"] == TransferStatus.CONFIRMED
    assert result["total"] == 1


def test_get_all_transfers_filtered_by_source_location():
    t = _make_transfer(id=1, source_location_id=10)

    repo = MagicMock()
    repo.paginate_by_spec.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [t.dict()],
    }
    handler = GetAllTransfersQueryHandler(repo)

    result = handler.handle(GetAllTransfersQuery(source_location_id=10))

    repo.paginate_by_spec.assert_called_once()
    assert len(result["items"]) == 1
    assert result["items"][0]["source_location_id"] == 10
    assert result["total"] == 1


# ---------------------------------------------------------------------------
# GetTransferByIdQueryHandler
# ---------------------------------------------------------------------------


def test_get_transfer_by_id_success():
    t = _make_transfer(id=1)
    repo = MagicMock()
    repo.get_by_id.return_value = t
    handler = GetTransferByIdQueryHandler(repo)

    result = handler.handle(GetTransferByIdQuery(id=1))

    assert result["id"] == 1
    assert result["source_location_id"] == 10
    assert result["destination_location_id"] == 20


def test_get_transfer_by_id_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = GetTransferByIdQueryHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(GetTransferByIdQuery(id=99))


# ---------------------------------------------------------------------------
# GetTransferItemsQueryHandler
# ---------------------------------------------------------------------------


def test_get_transfer_items_success():
    item1 = _make_item(id=1, quantity=10)
    item2 = _make_item(id=2, quantity=5)

    item_repo = MagicMock()
    item_repo.filter_by.return_value = [item1, item2]
    handler = GetTransferItemsQueryHandler(item_repo, MagicMock())

    result = handler.handle(GetTransferItemsQuery(transfer_id=1))

    item_repo.filter_by.assert_called_once_with(transfer_id=1)
    assert len(result) == 2
    assert result[0]["quantity"] == 10
    assert result[1]["quantity"] == 5


def test_get_transfer_items_empty():
    item_repo = MagicMock()
    item_repo.filter_by.return_value = []
    handler = GetTransferItemsQueryHandler(item_repo, MagicMock())

    result = handler.handle(GetTransferItemsQuery(transfer_id=99))

    assert result == []
