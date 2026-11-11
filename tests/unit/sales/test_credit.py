"""Ventas a crédito (S5.5): la parte CREDIT de los pagos queda en la cuenta del
cliente y el estado de pago es el de esa cuenta"""

from decimal import Decimal

import pytest

from src.sales.domain.entities import (
    Payment,
    PaymentMethod,
    PaymentStatus,
    Sale,
    SaleStatus,
)
from src.sales.domain.events import sale_payments_data
from src.sales.domain.exceptions import (
    CreditCustomerRequiredError,
    InsufficientPaymentError,
    PaymentExceedsBalanceError,
)


def _payment(amount: str, method=PaymentMethod.CASH) -> Payment:
    return Payment(sale_id=1, amount=Decimal(amount), payment_method=method)


def test_settle_says_what_is_left_on_credit_and_leaves_the_status_to_the_account():
    sale = Sale(id=1, customer_id=7, total=Decimal("100"))
    cash = _payment("30")
    credit = _payment("70", PaymentMethod.CREDIT)

    assert sale.settle([cash, credit]) == Decimal("70")
    # The receivable decides it (owe_on_account), not settle
    assert sale.payment_status == PaymentStatus.PENDING


def test_settle_without_credit_leaves_it_paid():
    sale = Sale(id=1, customer_id=7, total=Decimal("100"))

    assert sale.settle([_payment("100")]) == Decimal("0")
    assert sale.payment_status == PaymentStatus.PAID


def test_credit_counts_to_cover_the_total():
    sale = Sale(id=1, customer_id=7, total=Decimal("100"))
    with pytest.raises(InsufficientPaymentError):
        sale.settle([_payment("30"), _payment("60", PaymentMethod.CREDIT)])


def test_credit_cant_exceed_what_is_owed():
    sale = Sale(id=1, customer_id=7, total=Decimal("100"))
    with pytest.raises(PaymentExceedsBalanceError):
        sale.settle([_payment("101", PaymentMethod.CREDIT)])


def test_a_final_consumer_doesnt_buy_on_credit():
    sale = Sale(id=1, customer_id=None, is_final_consumer=True, total=Decimal("20"))
    with pytest.raises(CreditCustomerRequiredError):
        sale.settle([_payment("20", PaymentMethod.CREDIT)])
    with pytest.raises(CreditCustomerRequiredError):
        sale.take_payment(_payment("20", PaymentMethod.CREDIT), [])


def test_a_sale_on_credit_is_confirmed_without_being_paid():
    sale = Sale(id=1, customer_id=7, total=Decimal("100"))
    sale.settle([_payment("100", PaymentMethod.CREDIT)])
    sale.owe_on_account(Decimal("100"))

    sale.confirm("V-001-000001", on_credit=True)

    assert sale.status == SaleStatus.CONFIRMED
    assert sale.payment_status == PaymentStatus.PENDING


@pytest.mark.parametrize(
    ("balance", "status"),
    [
        (Decimal("100"), PaymentStatus.PENDING),
        (Decimal("40"), PaymentStatus.PARTIAL),
        (Decimal("0"), PaymentStatus.PAID),
    ],
)
def test_its_payment_status_follows_its_receivable(balance, status):
    sale = Sale(id=1, customer_id=7, total=Decimal("100"))

    sale.owe_on_account(balance)

    assert sale.payment_status == status


def test_a_down_payment_leaves_it_partial():
    sale = Sale(id=1, customer_id=7, total=Decimal("100"))
    sale.settle([_payment("20"), _payment("80", PaymentMethod.CREDIT)])

    sale.owe_on_account(Decimal("80"))

    assert sale.payment_status == PaymentStatus.PARTIAL


def test_the_credit_payment_carries_its_terms_to_the_invoice():
    cash = _payment("20")
    credit = _payment("80", PaymentMethod.CREDIT)
    credit.term_days = 30

    assert sale_payments_data([cash, credit]) == [
        {"method": PaymentMethod.CASH, "amount": Decimal("20")},
        {"method": PaymentMethod.CREDIT, "amount": Decimal("80"), "term_days": 30},
    ]
