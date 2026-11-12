from decimal import Decimal
from typing import Any

import pytest

from src.purchasing.domain.entities import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    PurchaseReceipt,
    PurchaseReceiptItem,
    SupplierReturn,
    SupplierReturnItem,
    SupplierReturnStatus,
)
from src.purchasing.domain.exceptions import (
    EmptySupplierReturnError,
    ExceedsPendingQuantityError,
    ExceedsReturnableQuantityError,
    InvalidPurchaseOrderStatusError,
    InvalidSupplierReturnStatusError,
    SupplierReturnCreditExceedsTotalError,
)
from src.shared.domain.tax import TaxCode

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


def _taxed_item(**overrides) -> PurchaseOrderItem:
    item = _make_item(**overrides)
    item.recalculate_tax()
    return item


def test_recalculate_totals_sums_item_subtotals():
    po = _make_po()
    po.recalculate_totals(
        [
            _taxed_item(
                quantity_ordered=2, unit_cost=Decimal("10.00"), tax_code=TaxCode.VAT_0
            ),
            _taxed_item(
                id=2,
                quantity_ordered=3,
                unit_cost=Decimal("1.50"),
                tax_code=TaxCode.VAT_0,
            ),
        ]
    )
    assert (po.subtotal, po.tax, po.total) == (
        Decimal("24.50"),
        Decimal("0.00"),
        Decimal("24.50"),
    )


def test_an_order_with_15_and_0_percent_lines_taxes_each_rate():
    """Acceptance (S5.7): 10 × 2.50 at 15 % and 4 × 3.25 at 0 % make a
    subtotal of 38.00 with 3.75 of VAT, a total of 41.75"""
    po = _make_po()
    items = [
        _taxed_item(
            quantity_ordered=Decimal(10),
            unit_cost=Decimal("2.50"),
            tax_code=TaxCode.VAT_15,
        ),
        _taxed_item(
            id=2,
            quantity_ordered=Decimal(4),
            unit_cost=Decimal("3.25"),
            tax_code=TaxCode.VAT_0,
        ),
    ]

    po.recalculate_totals(items)

    assert (po.subtotal, po.tax, po.total) == (
        Decimal("38.00"),
        Decimal("3.75"),
        Decimal("41.75"),
    )
    assert PurchaseOrder.tax_breakdown(items) == {
        TaxCode.VAT_15: (Decimal("25.00"), Decimal("3.75")),
        TaxCode.VAT_0: (Decimal("13.00"), Decimal("0.00")),
    }


def test_the_vat_of_a_rate_is_rounded_once_for_its_lines():
    """Like a sale: the lines keep their VAT at full precision and each rate
    rounds their sum (0.1575 + 0.1575 = 0.315 → 0.32), not each line (0.16 +
    0.16)"""
    po = _make_po()
    items = [
        _taxed_item(quantity_ordered=Decimal(1), unit_cost=Decimal("1.05")),
        _taxed_item(id=2, quantity_ordered=Decimal(1), unit_cost=Decimal("1.05")),
    ]
    assert items[0].tax_amount == Decimal("0.1575")

    po.recalculate_totals(items)

    assert (po.subtotal, po.tax, po.total) == (
        Decimal("2.10"),
        Decimal("0.32"),
        Decimal("2.42"),
    )


def test_a_line_recalculates_its_vat_when_updated():
    item = _taxed_item(tax_code=TaxCode.VAT_5)
    item.update(quantity_ordered=Decimal(2), unit_cost=Decimal("10.00"))
    assert item.tax_amount == Decimal("1.00")


def test_a_receipt_owes_what_it_received_with_its_vat():
    """Half of a line at 15 % and all of one at 0 %: the receipt takes the
    lines' costs and taxes each rate"""
    taxed = _taxed_item(quantity_ordered=Decimal(10), unit_cost=Decimal("2.50"))
    exempt = _taxed_item(
        id=2,
        quantity_ordered=Decimal(4),
        unit_cost=Decimal("3.25"),
        tax_code=TaxCode.EXEMPT,
    )
    receipt = PurchaseReceipt(purchase_order_id=1)

    receipt.recalculate_totals(
        [taxed.taxed_line(Decimal(5)), exempt.taxed_line(Decimal(4))]
    )

    assert (receipt.subtotal, receipt.tax, receipt.total) == (
        Decimal("25.50"),
        Decimal("1.88"),
        Decimal("27.38"),
    )


def test_a_line_returns_at_most_what_it_received_and_was_not_returned():
    item = _make_item(quantity_ordered=Decimal(10), quantity_received=Decimal(6))
    item.return_goods(Decimal(4))
    assert (item.quantity_returned, item.quantity_returnable) == (
        Decimal(4),
        Decimal(2),
    )

    with pytest.raises(ExceedsReturnableQuantityError, match="Only 2 units"):
        item.return_goods(Decimal(3))


# ---------------------------------------------------------------------------
# SupplierReturn (S5.7)
# ---------------------------------------------------------------------------


def _return(**overrides) -> SupplierReturn:
    defaults: dict[str, Any] = {
        "id": 1,
        "supplier_id": 10,
        "purchase_order_id": 1,
        "number": "DP-2026-0001",
    }
    defaults.update(overrides)
    return SupplierReturn(**defaults)


def test_a_return_line_takes_the_order_lines_cost_vat_and_presentation():
    order_item = _taxed_item(
        id=7,
        quantity_ordered=Decimal(5),
        quantity_received=Decimal(5),
        unit_cost=Decimal("30.00"),
        tax_code=TaxCode.VAT_15,
        presentation_id=3,
        unit_factor=Decimal(12),
    )

    line = SupplierReturnItem.of(1, order_item, Decimal(2), location_id=4)

    assert (line.purchase_order_item_id, line.product_id, line.presentation_id) == (
        7,
        5,
        3,
    )
    assert (line.unit_cost, line.tax_code, line.unit_factor) == (
        Decimal("30.00"),
        TaxCode.VAT_15,
        Decimal(12),
    )
    assert (line.subtotal, line.tax_amount, line.base_quantity) == (
        Decimal("60.00"),
        Decimal("9.00"),
        Decimal(24),
    )


def test_a_return_totals_its_lines_by_rate():
    taxed = _taxed_item(id=1, unit_cost=Decimal("2.50"), quantity_received=10)
    exempt = _taxed_item(
        id=2, unit_cost=Decimal("3.25"), quantity_received=4, tax_code=TaxCode.VAT_0
    )
    supplier_return = _return()

    supplier_return.recalculate_totals(
        [
            SupplierReturnItem.of(1, taxed, Decimal(2), None),
            SupplierReturnItem.of(1, exempt, Decimal(1), None),
        ]
    )

    assert (supplier_return.subtotal, supplier_return.tax, supplier_return.total) == (
        Decimal("8.25"),
        Decimal("0.75"),
        Decimal("9.00"),
    )


def test_confirming_a_return_needs_lines_and_a_draft():
    supplier_return = _return()
    with pytest.raises(EmptySupplierReturnError):
        supplier_return.confirm(0, None, "Ana")

    supplier_return.confirm(2, "001-001-000000045", "Ana")
    assert supplier_return.status == SupplierReturnStatus.CONFIRMED
    assert supplier_return.supplier_credit_note_number == "001-001-000000045"
    assert supplier_return.confirmed_by == "Ana"
    assert supplier_return.confirmed_at is not None

    with pytest.raises(InvalidSupplierReturnStatusError):
        supplier_return.confirm(2, None, "Ana")
    with pytest.raises(InvalidSupplierReturnStatusError):
        supplier_return.update_notes("otra")


def test_what_a_return_does_not_credit_is_refunded_by_the_supplier():
    supplier_return = _return(total=Decimal("50.00"))
    supplier_return.record_credit(Decimal("30.00"))
    assert supplier_return.refund_due == Decimal("20.00")

    with pytest.raises(SupplierReturnCreditExceedsTotalError):
        supplier_return.record_credit(Decimal("50.01"))


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
        quantity_received=Decimal(3),
        location_id=2,
    )
    assert ri.quantity_received == 3
    assert ri.location_id == 2


def test_item_receive_adds_to_received_quantity():
    item = _make_item(quantity_ordered=10, quantity_received=4)
    item.receive(Decimal(6))
    assert (item.quantity_received, item.quantity_pending) == (10, 0)


def test_item_cannot_receive_more_than_pending():
    item = _make_item(quantity_ordered=10, quantity_received=4)
    with pytest.raises(ExceedsPendingQuantityError, match="Only 6 units are pending"):
        item.receive(Decimal(7))
    assert item.quantity_received == 4
