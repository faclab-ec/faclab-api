from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.receivables.domain.allocation import (
    AgingBucket,
    aging_bucket,
    allocate_fifo,
    allocate_manual,
)
from src.receivables.domain.entities import (
    CustomerPayment,
    Receivable,
    ReceivableStatus,
)
from src.receivables.domain.exceptions import (
    CreditPaymentNotAllowedError,
    CustomerPaymentExceedsBalanceError,
    PaymentApplicationMismatchError,
    ReceivableHasPaymentsError,
    ReceivableNotOpenError,
)
from src.sales.domain.entities import PaymentMethod
from src.shared.domain.exceptions import InvalidValueError

TODAY = date(2026, 11, 11)


def _receivable(id: int, balance: str, due_in: int = 30, amount: str | None = None):
    receivable = Receivable.open(
        customer_id=7,
        sale_id=100 + id,
        amount=Decimal(amount or balance),
        term_days=30,
        issued_on=TODAY + timedelta(days=due_in - 30),
    )
    receivable.id = id
    receivable.balance = Decimal(balance)
    return receivable


def test_a_receivable_falls_due_after_the_customers_terms():
    receivable = Receivable.open(
        customer_id=7,
        sale_id=1,
        amount=Decimal("80.004"),
        term_days=30,
        issued_on=TODAY,
    )

    assert receivable.due_on == date(2026, 12, 11)
    assert receivable.amount == receivable.balance == Decimal("80.00")
    assert receivable.status == ReceivableStatus.OPEN


def test_a_receivable_needs_a_positive_amount():
    with pytest.raises(InvalidValueError):
        Receivable.open(
            customer_id=7, sale_id=1, amount=Decimal("0"), term_days=0, issued_on=TODAY
        )


def test_crediting_lowers_the_balance_until_it_is_paid():
    receivable = _receivable(1, "100")

    receivable.credit(Decimal("60"))
    assert (receivable.balance, receivable.status) == (
        Decimal("40"),
        ReceivableStatus.OPEN,
    )

    receivable.credit(Decimal("40"))
    assert (receivable.balance, receivable.status) == (
        Decimal("0"),
        ReceivableStatus.PAID,
    )
    with pytest.raises(ReceivableNotOpenError):
        receivable.credit(Decimal("1"))


def test_crediting_more_than_the_balance_fails():
    with pytest.raises(InvalidValueError):
        _receivable(1, "10").credit(Decimal("10.01"))


def test_a_receivable_is_cancelled_only_while_nothing_lowered_it():
    receivable = _receivable(1, "100")
    with pytest.raises(ReceivableHasPaymentsError):
        receivable.cancel(has_applications=True)

    receivable.cancel(has_applications=False)

    assert receivable.status == ReceivableStatus.CANCELLED
    assert receivable.balance == Decimal("0")
    assert receivable.cancelled_at is not None


def test_fifo_pays_the_one_due_first():
    later = _receivable(1, "50", due_in=20)
    sooner = _receivable(2, "30", due_in=-5)
    same_day = _receivable(3, "40", due_in=20)

    allocations = allocate_fifo(Decimal("100"), [later, same_day, sooner])

    assert [(a.receivable.id, a.amount) for a in allocations] == [
        (2, Decimal("30")),
        (1, Decimal("50")),
        (3, Decimal("20")),
    ]


def test_a_payment_cant_exceed_what_is_owed():
    with pytest.raises(CustomerPaymentExceedsBalanceError):
        allocate_fifo(Decimal("80.01"), [_receivable(1, "50"), _receivable(2, "30")])


def test_a_manual_application_pays_what_it_says():
    first, second = _receivable(1, "50", due_in=-10), _receivable(2, "30")

    allocations = allocate_manual(
        Decimal("40"), [first, second], {2: Decimal("30"), 1: Decimal("10")}
    )

    # In the FIFO order, the one they are locked and updated in
    assert [(a.receivable.id, a.amount) for a in allocations] == [
        (1, Decimal("10")),
        (2, Decimal("30")),
    ]


@pytest.mark.parametrize(
    ("amount", "requested"),
    [
        # They don't add up to the payment
        ("40", {1: Decimal("30")}),
        # More than a receivable's balance
        ("60", {1: Decimal("60")}),
    ],
)
def test_a_manual_application_must_match(amount, requested):
    with pytest.raises(PaymentApplicationMismatchError):
        allocate_manual(Decimal(amount), [_receivable(1, "50")], requested)


def test_a_manual_application_only_pays_open_receivables_of_the_customer():
    with pytest.raises(ReceivableNotOpenError):
        allocate_manual(Decimal("10"), [_receivable(1, "50")], {99: Decimal("10")})


@pytest.mark.parametrize(
    ("days", "bucket"),
    [
        (-15, AgingBucket.NOT_DUE),
        (0, AgingBucket.NOT_DUE),
        (1, AgingBucket.DAYS_1_30),
        (30, AgingBucket.DAYS_1_30),
        (31, AgingBucket.DAYS_31_60),
        (60, AgingBucket.DAYS_31_60),
        (61, AgingBucket.DAYS_61_90),
        (90, AgingBucket.DAYS_61_90),
        (91, AgingBucket.OVER_90),
    ],
)
def test_aging_buckets_by_days_past_due(days, bucket):
    assert aging_bucket(days) == bucket


def test_a_payment_on_account_is_never_on_credit_nor_zero():
    with pytest.raises(CreditPaymentNotAllowedError):
        CustomerPayment(
            customer_id=7, amount=Decimal("10"), payment_method=PaymentMethod.CREDIT
        )
    with pytest.raises(InvalidValueError):
        CustomerPayment(
            customer_id=7, amount=Decimal("0.001"), payment_method=PaymentMethod.CASH
        )
