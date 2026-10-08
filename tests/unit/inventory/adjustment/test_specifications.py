"""Unit tests for AdjustmentsByStatus and AdjustmentsByWarehouse specifications"""

from typing import Any

from src.inventory.adjustment.domain.entities import (
    AdjustmentReason,
    AdjustmentStatus,
    InventoryAdjustment,
)
from src.inventory.adjustment.domain.specifications import (
    AdjustmentsByStatus,
    AdjustmentsByWarehouse,
)


def _make_adjustment(**overrides) -> InventoryAdjustment:
    defaults: dict[str, Any] = {
        "id": 1,
        "warehouse_id": 10,
        "reason": AdjustmentReason.PHYSICAL_COUNT,
        "status": AdjustmentStatus.DRAFT,
    }
    defaults.update(overrides)
    return InventoryAdjustment(**defaults)


# ---------------------------------------------------------------------------
# AdjustmentsByStatus
# ---------------------------------------------------------------------------


def test_adjustments_by_status_matches():
    adj = _make_adjustment(status=AdjustmentStatus.DRAFT)
    spec = AdjustmentsByStatus(AdjustmentStatus.DRAFT)
    assert spec.is_satisfied_by(adj) is True


def test_adjustments_by_status_not_matches():
    adj = _make_adjustment(status=AdjustmentStatus.CONFIRMED)
    spec = AdjustmentsByStatus(AdjustmentStatus.DRAFT)
    assert spec.is_satisfied_by(adj) is False


def test_adjustments_by_status_to_query_criteria():
    spec = AdjustmentsByStatus(AdjustmentStatus.DRAFT)
    criteria = spec.to_query_criteria()
    assert len(criteria) == 1


# ---------------------------------------------------------------------------
# AdjustmentsByWarehouse
# ---------------------------------------------------------------------------


def test_adjustments_by_warehouse_matches():
    adj = _make_adjustment(warehouse_id=10)
    spec = AdjustmentsByWarehouse(warehouse_id=10)
    assert spec.is_satisfied_by(adj) is True


def test_adjustments_by_warehouse_not_matches():
    adj = _make_adjustment(warehouse_id=10)
    spec = AdjustmentsByWarehouse(warehouse_id=99)
    assert spec.is_satisfied_by(adj) is False


def test_adjustments_by_warehouse_to_query_criteria():
    spec = AdjustmentsByWarehouse(warehouse_id=10)
    criteria = spec.to_query_criteria()
    assert len(criteria) == 1
