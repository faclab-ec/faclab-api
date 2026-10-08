"""Unit tests for InventoryAdjustment and AdjustmentItem entities"""

from typing import Any

import pytest

from src.inventory.adjustment.domain.entities import (
    AdjustmentItem,
    AdjustmentReason,
    AdjustmentStatus,
    InventoryAdjustment,
)
from src.shared.domain.exceptions import DomainError


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
    confirmed = adj.confirm()
    assert confirmed.status == AdjustmentStatus.CONFIRMED


def test_confirm_confirmed_adjustment_raises():
    adj = _make_adjustment(status=AdjustmentStatus.CONFIRMED)
    with pytest.raises(DomainError):
        adj.confirm()


def test_confirm_cancelled_adjustment_raises():
    adj = _make_adjustment(status=AdjustmentStatus.CANCELLED)
    with pytest.raises(DomainError):
        adj.confirm()


# ---------------------------------------------------------------------------
# InventoryAdjustment.cancel()
# ---------------------------------------------------------------------------


def test_cancel_draft_adjustment():
    adj = _make_adjustment(status=AdjustmentStatus.DRAFT)
    cancelled = adj.cancel()
    assert cancelled.status == AdjustmentStatus.CANCELLED


def test_cancel_confirmed_adjustment_raises():
    adj = _make_adjustment(status=AdjustmentStatus.CONFIRMED)
    with pytest.raises(DomainError):
        adj.cancel()


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
