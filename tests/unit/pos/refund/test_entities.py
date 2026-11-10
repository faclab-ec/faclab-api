from decimal import Decimal

import pytest

from src.pos.refund.domain.entities import (
    Refund,
    RefundItem,
    RefundPayment,
    RefundStatus,
)
from src.pos.refund.domain.exceptions import InvalidRefundStatusError
from src.sales.domain.entities import PaymentMethod

# --- Refund ---


def test_refund_complete_pending_to_completed():
    refund = Refund(original_sale_id=1, id=1)
    refund.complete()
    assert refund.status == RefundStatus.COMPLETED
    assert refund.refund_date is not None


def test_refund_cancel_pending_to_cancelled():
    refund = Refund(original_sale_id=1, id=1)
    refund.cancel()
    assert refund.status == RefundStatus.CANCELLED


def test_refund_complete_from_completed_fails():
    refund = Refund(original_sale_id=1, status=RefundStatus.COMPLETED, id=1)
    with pytest.raises(InvalidRefundStatusError):
        refund.complete()


def test_refund_complete_from_cancelled_fails():
    refund = Refund(original_sale_id=1, status=RefundStatus.CANCELLED, id=1)
    with pytest.raises(InvalidRefundStatusError):
        refund.complete()


def test_refund_cancel_from_completed_fails():
    refund = Refund(original_sale_id=1, status=RefundStatus.COMPLETED, id=1)
    with pytest.raises(InvalidRefundStatusError):
        refund.cancel()


def test_refund_cancel_from_cancelled_fails():
    refund = Refund(original_sale_id=1, status=RefundStatus.CANCELLED, id=1)
    with pytest.raises(InvalidRefundStatusError):
        refund.cancel()


# --- RefundItem ---


def test_refund_item_subtotal_no_discount():
    item = RefundItem(
        refund_id=1,
        original_sale_item_id=1,
        product_id=1,
        quantity=Decimal(3),
        unit_price=Decimal("10.00"),
    )
    assert item.subtotal == Decimal("30.00")


def test_refund_item_subtotal_with_discount():
    item = RefundItem(
        refund_id=1,
        original_sale_item_id=1,
        product_id=1,
        quantity=Decimal(2),
        unit_price=Decimal("100.00"),
        discount=Decimal("10"),
    )
    assert item.subtotal == Decimal("180.00")


# --- RefundPayment ---


def test_refund_payment_positive_amount():
    payment = RefundPayment(
        refund_id=1,
        amount=Decimal("50.00"),
        payment_method=PaymentMethod.CASH,
    )
    assert payment.amount == Decimal("50.00")


def test_refund_payment_zero_amount_fails():
    with pytest.raises(ValueError):
        RefundPayment(
            refund_id=1,
            amount=Decimal("0"),
            payment_method=PaymentMethod.CASH,
        )


def test_refund_payment_negative_amount_fails():
    with pytest.raises(ValueError):
        RefundPayment(
            refund_id=1,
            amount=Decimal("-10"),
            payment_method=PaymentMethod.CASH,
        )
