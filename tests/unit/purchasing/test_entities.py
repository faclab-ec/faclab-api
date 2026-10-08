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
from src.purchasing.domain.exceptions import (
    ExceedsPendingQuantityError,
    InvalidPurchaseOrderStatusError,
)

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
    po.send()
    assert po.status == PurchaseOrderStatus.SENT


def test_purchase_order_send_from_non_draft_raises():
    po = _make_po(status=PurchaseOrderStatus.SENT)
    with pytest.raises(InvalidPurchaseOrderStatusError, match="Cannot send"):
        po.send()


def test_purchase_order_send_from_partial_raises():
    po = _make_po(status=PurchaseOrderStatus.PARTIAL)
    with pytest.raises(InvalidPurchaseOrderStatusError):
        po.send()


def test_purchase_order_cancel_from_draft():
    po = _make_po(status=PurchaseOrderStatus.DRAFT)
    po.cancel()
    assert po.status == PurchaseOrderStatus.CANCELLED


def test_purchase_order_cancel_from_sent():
    po = _make_po(status=PurchaseOrderStatus.SENT)
    po.cancel()
    assert po.status == PurchaseOrderStatus.CANCELLED


def test_purchase_order_cancel_from_partial():
    po = _make_po(status=PurchaseOrderStatus.PARTIAL)
    po.cancel()
    assert po.status == PurchaseOrderStatus.CANCELLED


def test_purchase_order_cancel_from_received_raises():
    po = _make_po(status=PurchaseOrderStatus.RECEIVED)
    with pytest.raises(InvalidPurchaseOrderStatusError, match="status 'received'"):
        po.cancel()


def test_purchase_order_cancel_already_cancelled_raises():
    po = _make_po(status=PurchaseOrderStatus.CANCELLED)
    with pytest.raises(InvalidPurchaseOrderStatusError, match="status 'cancelled'"):
        po.cancel()


@pytest.mark.parametrize(
    "status", [PurchaseOrderStatus.SENT, PurchaseOrderStatus.PARTIAL]
)
def test_reception_status_is_partial_while_items_are_pending(status):
    po = _make_po(status=status)
    po.update_reception_status(
        [_make_item(quantity_received=10), _make_item(id=2, quantity_received=3)]
    )
    assert po.status == PurchaseOrderStatus.PARTIAL


def test_reception_status_is_received_when_nothing_is_pending():
    po = _make_po(status=PurchaseOrderStatus.PARTIAL)
    po.update_reception_status([_make_item(quantity_received=10)])
    assert po.status == PurchaseOrderStatus.RECEIVED


@pytest.mark.parametrize(
    "status",
    [
        PurchaseOrderStatus.DRAFT,
        PurchaseOrderStatus.RECEIVED,
        PurchaseOrderStatus.CANCELLED,
    ],
)
def test_only_sent_or_partial_orders_are_receivable(status):
    po = _make_po(status=status)
    with pytest.raises(InvalidPurchaseOrderStatusError, match="Cannot receive"):
        po.ensure_receivable()


def test_update_details_only_in_draft():
    po = _make_po(status=PurchaseOrderStatus.DRAFT)
    po.update_details(supplier_id=20, notes="n", expected_date=None)
    assert (po.supplier_id, po.notes) == (20, "n")

    po.send()
    with pytest.raises(InvalidPurchaseOrderStatusError, match="Cannot update"):
        po.update_details(supplier_id=30, notes=None, expected_date=None)


def test_recalculate_totals_sums_item_subtotals():
    po = _make_po()
    po.recalculate_totals(
        [
            _make_item(quantity_ordered=2, unit_cost=Decimal("10.00")),
            _make_item(id=2, quantity_ordered=3, unit_cost=Decimal("1.50")),
        ]
    )
    assert (po.subtotal, po.tax, po.total) == (
        Decimal("24.50"),
        Decimal("0.00"),
        Decimal("24.50"),
    )


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


def test_item_receive_adds_to_received_quantity():
    item = _make_item(quantity_ordered=10, quantity_received=4)
    item.receive(6)
    assert (item.quantity_received, item.quantity_pending) == (10, 0)


def test_item_cannot_receive_more_than_pending():
    item = _make_item(quantity_ordered=10, quantity_received=4)
    with pytest.raises(ExceedsPendingQuantityError, match="Only 6 units are pending"):
        item.receive(7)
    assert item.quantity_received == 4
