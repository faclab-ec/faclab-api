"""Unit tests for inventory adjustment query handlers"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.inventory.adjustment.app.queries.adjustment import (
    GetAdjustmentByIdQuery,
    GetAdjustmentByIdQueryHandler,
    GetAdjustmentItemsQuery,
    GetAdjustmentItemsQueryHandler,
    GetAllAdjustmentsQuery,
    GetAllAdjustmentsQueryHandler,
)
from src.inventory.adjustment.domain.entities import (
    AdjustmentItem,
    AdjustmentReason,
    AdjustmentStatus,
    InventoryAdjustment,
)
from src.shared.domain.exceptions import NotFoundError


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
        "actual_quantity": 115,
    }
    defaults.update(overrides)
    return AdjustmentItem(**defaults)


# ---------------------------------------------------------------------------
# GetAllAdjustmentsQueryHandler
# ---------------------------------------------------------------------------


def test_get_all_adjustments_no_filters():
    adj1 = _make_adjustment(id=1)
    adj2 = _make_adjustment(id=2, status=AdjustmentStatus.CONFIRMED)

    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [adj1.dict(), adj2.dict()],
    }
    handler = GetAllAdjustmentsQueryHandler(repo)

    result = handler.handle(GetAllAdjustmentsQuery())

    repo.paginate.assert_called_once()
    assert len(result["items"]) == 2
    assert result["total"] == 2


def test_get_all_adjustments_filtered_by_status():
    adj = _make_adjustment(id=1, status=AdjustmentStatus.DRAFT)

    repo = MagicMock()
    repo.paginate_by_spec.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [adj.dict()],
    }
    handler = GetAllAdjustmentsQueryHandler(repo)

    result = handler.handle(GetAllAdjustmentsQuery(status="draft"))

    repo.paginate_by_spec.assert_called_once()
    assert len(result["items"]) == 1
    assert result["items"][0]["status"] == AdjustmentStatus.DRAFT
    assert result["total"] == 1


def test_get_all_adjustments_filtered_by_warehouse():
    adj = _make_adjustment(id=1, warehouse_id=10)

    repo = MagicMock()
    repo.paginate_by_spec.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [adj.dict()],
    }
    handler = GetAllAdjustmentsQueryHandler(repo)

    result = handler.handle(GetAllAdjustmentsQuery(warehouse_id=10))

    repo.paginate_by_spec.assert_called_once()
    assert len(result["items"]) == 1
    assert result["items"][0]["warehouse_id"] == 10
    assert result["total"] == 1


# ---------------------------------------------------------------------------
# GetAdjustmentByIdQueryHandler
# ---------------------------------------------------------------------------


def test_get_adjustment_by_id_success():
    adj = _make_adjustment(id=1)
    repo = MagicMock()
    repo.get_by_id.return_value = adj
    handler = GetAdjustmentByIdQueryHandler(repo)

    result = handler.handle(GetAdjustmentByIdQuery(id=1))

    assert result["id"] == 1
    assert result["warehouse_id"] == 10


def test_get_adjustment_by_id_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = GetAdjustmentByIdQueryHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(GetAdjustmentByIdQuery(id=99))


# ---------------------------------------------------------------------------
# GetAdjustmentItemsQueryHandler
# ---------------------------------------------------------------------------


def test_get_adjustment_items_includes_difference():
    item1 = _make_item(id=1, expected_quantity=100, actual_quantity=115)
    item2 = _make_item(id=2, expected_quantity=50, actual_quantity=45)

    item_repo = MagicMock()
    item_repo.filter_by.return_value = [item1, item2]
    handler = GetAdjustmentItemsQueryHandler(item_repo)

    result = handler.handle(GetAdjustmentItemsQuery(adjustment_id=1))

    assert len(result) == 2
    assert result[0]["difference"] == 15
    assert result[1]["difference"] == -5
