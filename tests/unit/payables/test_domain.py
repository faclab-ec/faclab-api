"""Accounts payable (S5.7): what a receipt owes, its due date and how payments
and returns lower it"""

from datetime import date
from decimal import Decimal

import pytest

from src.payables.domain.allocation import (
    allocate_fifo,
    allocate_manual,
    allocate_return,
)
from src.payables.domain.entities import Payable, PayableStatus, SupplierPayment
from src.payables.domain.exceptions import (
    CreditPaymentNotAllowedError,
    PayableNotOpenError,
    SupplierPaymentApplicationMismatchError,
    SupplierPaymentExceedsBalanceError,
)
from src.sales.domain.entities import PaymentMethod
from src.shared.domain.exceptions import InvalidValueError


def _payable(id: int, balance: str, due_on: date, order: int = 1) -> Payable:
    payable = Payable.open(
        supplier_id=10,
        purchase_order_id=order,
        purchase_receipt_id=100 + id,
        amount=Decimal(balance),
        term_days=0,
        issued_on=due_on,
    )
    payable.id = id
    return payable


def test_a_payable_is_due_in_the_suppliers_terms():
    payable = Payable.open(
        supplier_id=10,
        purchase_order_id=1,
        purchase_receipt_id=4,
        amount=Decimal("14.375"),
        term_days=30,
        issued_on=date(2026, 11, 3),
        supplier_invoice_number="001-002-000000123",
    )

    assert payable.due_on == date(2026, 12, 3)
    assert (payable.amount, payable.balance) == (Decimal("14.38"), Decimal("14.38"))
    assert payable.days_overdue(date(2026, 12, 10)) == 7


def test_a_payable_needs_an_amount():
    with pytest.raises(InvalidValueError):
        Payable.open(
            supplier_id=10,
            purchase_order_id=1,
            purchase_receipt_id=4,
            amount=Decimal("0"),
            term_days=0,
            issued_on=date(2026, 11, 3),
        )


def test_crediting_a_payable_down_to_zero_pays_it():
    payable = _payable(1, "20.00", date(2026, 11, 1))
    payable.credit(Decimal("5.00"))
    assert (payable.balance, payable.status) == (Decimal("15.00"), PayableStatus.OPEN)
    payable.credit(Decimal("15.00"))
    assert (payable.balance, payable.status) == (Decimal("0.00"), PayableStatus.PAID)

    with pytest.raises(PayableNotOpenError):
        payable.credit(Decimal("1.00"))


def test_a_payment_goes_to_the_one_due_first():
    later = _payable(1, "30.00", date(2026, 12, 1))
    sooner = _payable(2, "20.00", date(2026, 11, 1))

    allocations = allocate_fifo(Decimal("25.00"), [later, sooner])

    assert [(a.payable.id, a.amount) for a in allocations] == [
        (2, Decimal("20.00")),
        (1, Decimal("5.00")),
    ]


def test_a_payment_cant_exceed_what_is_owed():
    with pytest.raises(SupplierPaymentExceedsBalanceError):
        allocate_fifo(Decimal("50.01"), [_payable(1, "50.00", date(2026, 11, 1))])


def test_a_manual_payment_adds_up_to_its_amount():
    one = _payable(1, "30.00", date(2026, 12, 1))
    two = _payable(2, "20.00", date(2026, 11, 1))

    allocations = allocate_manual(Decimal("25.00"), [one, two], {1: Decimal("25.00")})
    assert [(a.payable.id, a.amount) for a in allocations] == [(1, Decimal("25.00"))]

    with pytest.raises(SupplierPaymentApplicationMismatchError):
        allocate_manual(Decimal("25.00"), [one, two], {1: Decimal("20.00")})
    with pytest.raises(SupplierPaymentApplicationMismatchError):
        allocate_manual(Decimal("25.00"), [one, two], {2: Decimal("25.00")})
    with pytest.raises(PayableNotOpenError):
        allocate_manual(Decimal("5.00"), [one, two], {9: Decimal("5.00")})


def test_a_return_credits_its_orders_payables_first_and_keeps_the_rest():
    """The return of order 2 pays its own payable first, even if another one is
    due sooner, then the supplier's others; what doesn't fit isn't applied"""
    sooner_other_order = _payable(1, "10.00", date(2026, 10, 1), order=1)
    own = _payable(2, "15.00", date(2026, 11, 1), order=2)

    allocations = allocate_return(
        Decimal("40.00"), [sooner_other_order, own], purchase_order_id=2
    )

    assert [(a.payable.id, a.amount) for a in allocations] == [
        (2, Decimal("15.00")),
        (1, Decimal("10.00")),
    ]


def test_a_supplier_payment_is_positive_and_never_on_credit():
    payment = SupplierPayment(
        supplier_id=10, amount=Decimal("10.005"), payment_method=PaymentMethod.TRANSFER
    )
    assert payment.amount == Decimal("10.01")

    with pytest.raises(CreditPaymentNotAllowedError):
        SupplierPayment(
            supplier_id=10, amount=Decimal("1"), payment_method=PaymentMethod.CREDIT
        )
    with pytest.raises(InvalidValueError):
        SupplierPayment(
            supplier_id=10, amount=Decimal("0"), payment_method=PaymentMethod.CASH
        )
