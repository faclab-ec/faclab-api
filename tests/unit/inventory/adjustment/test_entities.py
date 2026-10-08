"""Unit tests for InventoryAdjustment and AdjustmentItem entities"""

from typing import Any

import pytest

from src.inventory.adjustment.domain.entities import (
    AdjustmentItem,
    AdjustmentReason,
    AdjustmentStatus,
    InventoryAdjustment,
)
from src.inventory.adjustment.domain.exceptions import InvalidAdjustmentStatusError


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
# InventoryAdjustment.confirm()
# ---------------------------------------------------------------------------


def test_confirm_draft_adjustment():
    adj = _make_adjustment(status=AdjustmentStatus.DRAFT)
    adj.confirm()
    assert adj.status == AdjustmentStatus.CONFIRMED


def test_confirm_confirmed_adjustment_raises():
    adj = _make_adjustment(status=AdjustmentStatus.CONFIRMED)
    with pytest.raises(InvalidAdjustmentStatusError):
        adj.confirm()


def test_confirm_cancelled_adjustment_raises():
    adj = _make_adjustment(status=AdjustmentStatus.CANCELLED)
    with pytest.raises(InvalidAdjustmentStatusError):
        adj.confirm()


# ---------------------------------------------------------------------------
# InventoryAdjustment.cancel()
# ---------------------------------------------------------------------------


def test_cancel_draft_adjustment():
    adj = _make_adjustment(status=AdjustmentStatus.DRAFT)
    adj.cancel()
    assert adj.status == AdjustmentStatus.CANCELLED


def test_cancel_confirmed_adjustment_raises():
    adj = _make_adjustment(status=AdjustmentStatus.CONFIRMED)
    with pytest.raises(InvalidAdjustmentStatusError):
        adj.cancel()


# ---------------------------------------------------------------------------
# InventoryAdjustment.update_details() / ensure_draft()
# ---------------------------------------------------------------------------


def test_update_details_keeps_fields_not_given():
    adj = _make_adjustment(notes="old", adjusted_by="ana")
    adj.update_details(notes="new")
    assert (adj.notes, adj.adjusted_by) == ("new", "ana")


@pytest.mark.parametrize(
    "status", [AdjustmentStatus.CONFIRMED, AdjustmentStatus.CANCELLED]
)
def test_only_draft_adjustments_can_be_edited(status):
    adj = _make_adjustment(status=status)
    with pytest.raises(InvalidAdjustmentStatusError):
        adj.update_details(notes="new")
    with pytest.raises(InvalidAdjustmentStatusError):
        adj.ensure_draft("agregar ítems a")


# ---------------------------------------------------------------------------
# AdjustmentItem.difference
# ---------------------------------------------------------------------------


def test_adjustment_item_difference_positive():
    item = _make_item(expected_quantity=100, actual_quantity=110)
    assert item.difference == 10


def test_adjustment_item_difference_negative():
    item = _make_item(expected_quantity=100, actual_quantity=85)
    assert item.difference == -15


def test_adjustment_item_difference_zero():
    item = _make_item(expected_quantity=50, actual_quantity=50)
    assert item.difference == 0


def test_adjustment_item_update_changes_only_given_fields():
    item = _make_item(actual_quantity=110, notes="n")
    item.update(actual_quantity=90)
    assert (item.actual_quantity, item.notes) == (90, "n")
