from decimal import Decimal
from typing import Any

import pytest

from src.purchasing.domain.entities import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    PurchaseReceipt,
    PurchaseReceiptItem,
)
from src.shared.domain.exceptions import DomainError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_po(**overrides) -> PurchaseOrder:
    defaults: dict[str, Any] = {
        "id": 1,
        "supplier_id": 10,
        "order_number": "PO-2026-0001",
        "status": PurchaseOrderStatus.DRAFT,
    }
    defaults.update(overrides)
    return PurchaseOrder(**defaults)


def _make_item(**overrides) -> PurchaseOrderItem:
    defaults: dict[str, Any] = {
        "id": 1,
        "purchase_order_id": 1,
        "product_id": 5,
        "quantity_ordered": 10,
        "unit_cost": Decimal("25.00"),
        "quantity_received": 0,
    }
    defaults.update(overrides)
    return PurchaseOrderItem(**defaults)


# ---------------------------------------------------------------------------
# PurchaseOrder lifecycle
# ---------------------------------------------------------------------------


def test_purchase_order_initial_status():
    po = _make_po()
    assert po.status == PurchaseOrderStatus.DRAFT


def test_purchase_order_send_from_draft():
    po = _make_po(status=PurchaseOrderStatus.DRAFT)
    sent = po.send()
    assert sent.status == PurchaseOrderStatus.SENT


def test_purchase_order_send_from_non_draft_raises():
    po = _make_po(status=PurchaseOrderStatus.SENT)
    with pytest.raises(DomainError, match="Only DRAFT orders can be sent"):
        po.send()


def test_purchase_order_send_from_partial_raises():
    po = _make_po(status=PurchaseOrderStatus.PARTIAL)
    with pytest.raises(DomainError):
        po.send()


def test_purchase_order_cancel_from_draft():
    po = _make_po(status=PurchaseOrderStatus.DRAFT)
    cancelled = po.cancel()
    assert cancelled.status == PurchaseOrderStatus.CANCELLED


def test_purchase_order_cancel_from_sent():
    po = _make_po(status=PurchaseOrderStatus.SENT)
    cancelled = po.cancel()
    assert cancelled.status == PurchaseOrderStatus.CANCELLED


def test_purchase_order_cancel_from_partial():
    po = _make_po(status=PurchaseOrderStatus.PARTIAL)
    cancelled = po.cancel()
    assert cancelled.status == PurchaseOrderStatus.CANCELLED


def test_purchase_order_cancel_from_received_raises():
    po = _make_po(status=PurchaseOrderStatus.RECEIVED)
    with pytest.raises(DomainError, match="already been received"):
        po.cancel()


def test_purchase_order_cancel_already_cancelled_raises():
    po = _make_po(status=PurchaseOrderStatus.CANCELLED)
    with pytest.raises(DomainError, match="already cancelled"):
        po.cancel()


def test_purchase_order_mark_partial():
    po = _make_po(status=PurchaseOrderStatus.SENT)
    partial = po.mark_partial()
    assert partial.status == PurchaseOrderStatus.PARTIAL


def test_purchase_order_mark_received():
    po = _make_po(status=PurchaseOrderStatus.SENT)
    received = po.mark_received()
    assert received.status == PurchaseOrderStatus.RECEIVED


def test_purchase_order_is_immutable():
    po = _make_po(status=PurchaseOrderStatus.DRAFT)
    sent = po.send()
    assert po.status == PurchaseOrderStatus.DRAFT  # original unchanged
    assert sent.status == PurchaseOrderStatus.SENT


# ---------------------------------------------------------------------------
# PurchaseOrderItem properties
# ---------------------------------------------------------------------------


def test_item_quantity_pending_all_pending():
    item = _make_item(quantity_ordered=10, quantity_received=0)
    assert item.quantity_pending == 10


def test_item_quantity_pending_partial():
    item = _make_item(quantity_ordered=10, quantity_received=4)
    assert item.quantity_pending == 6


def test_item_quantity_pending_fully_received():
    item = _make_item(quantity_ordered=10, quantity_received=10)
    assert item.quantity_pending == 0


def test_item_subtotal():
    item = _make_item(quantity_ordered=5, unit_cost=Decimal("20.00"))
    assert item.subtotal == Decimal("100.00")


# ---------------------------------------------------------------------------
# PurchaseReceipt + PurchaseReceiptItem construction
# ---------------------------------------------------------------------------


def test_purchase_receipt_creation():
    receipt = PurchaseReceipt(id=1, purchase_order_id=1)
    assert receipt.purchase_order_id == 1


def test_purchase_receipt_item_creation():
    ri = PurchaseReceiptItem(
        id=1,
        purchase_receipt_id=1,
        purchase_order_item_id=1,
        product_id=5,
        quantity_received=3,
        location_id=2,
    )
    assert ri.quantity_received == 3
    assert ri.location_id == 2
