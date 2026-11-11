"""CustomerCredit: abre la cuenta de una venta a crédito dentro del cupo, acredita
las devoluciones y anula la cuenta de una venta anulada (S5.5)"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest

from src.receivables.domain.entities import (
    Receivable,
    ReceivableApplication,
    ReceivableApplicationKind,
    ReceivableStatus,
)
from src.receivables.domain.exceptions import (
    CreditLimitExceededError,
    CustomerWithoutCreditError,
    ReceivableHasPaymentsError,
)
from src.sales.domain.entities import Payment, PaymentMethod, PaymentStatus, Sale
from tests.receivables import credit_customer, customer_credit


def _sale(id: int = 1, total: str = "100", customer_id: int | None = 7) -> Sale:
    return Sale(id=id, customer_id=customer_id, total=Decimal(total), branch_id=1)


def _pays(sale: Sale, cash: str = "0", credit: str = "100") -> list[Payment]:
    payments = []
    if Decimal(cash):
        payments.append(
            Payment(sale_id=1, amount=Decimal(cash), payment_method=PaymentMethod.CASH)
        )
    payments.append(
        Payment(sale_id=1, amount=Decimal(credit), payment_method=PaymentMethod.CREDIT)
    )
    sale.settle(payments)
    return payments


def _owing(balance: str, sale_id: int = 50, customer_id: int = 7) -> Receivable:
    receivable = Receivable.open(
        customer_id=customer_id,
        sale_id=sale_id,
        amount=Decimal(balance),
        term_days=30,
        issued_on=date.today(),
    )
    receivable.id = sale_id
    return receivable


def test_a_sale_on_credit_opens_a_receivable_due_by_the_customers_terms():
    credit = customer_credit([credit_customer(payment_terms=45)])
    sale = _sale()
    payments = _pays(sale, cash="20", credit="80")

    receivable = credit.open(sale, payments)

    assert receivable is not None
    assert (receivable.amount, receivable.balance) == (Decimal("80"), Decimal("80"))
    assert receivable.due_on == date.today() + timedelta(days=45)
    assert (receivable.sale_id, receivable.customer_id, receivable.branch_id) == (
        1,
        7,
        1,
    )
    # The invoice's plazo, and the sale pending its collection
    assert payments[1].term_days == 45
    assert payments[0].term_days is None
    assert sale.payment_status == PaymentStatus.PARTIAL
    # The customer's row, locked so its outstanding balance is read by one sale
    assert credit.customers.locked == [{"id": 7}]


def test_a_sale_without_credit_opens_nothing_nor_locks_the_customer():
    credit = customer_credit([credit_customer()])
    sale = _sale()
    payments = [
        Payment(sale_id=1, amount=Decimal("100"), payment_method=PaymentMethod.CASH)
    ]
    sale.settle(payments)

    assert credit.open(sale, payments) is None
    assert credit.customers.locked == []


def test_the_credit_limit_counts_what_the_customer_already_owes():
    credit = customer_credit(
        [credit_customer(credit_limit=Decimal("500"))], receivables=[_owing("420")]
    )

    sale = _sale(total="80")
    assert credit.open(sale, _pays(sale, credit="80")) is not None

    sale = _sale(id=2, total="0.01")
    with pytest.raises(CreditLimitExceededError) as error:
        credit.open(sale, _pays(sale, credit="0.01"))
    assert error.value.error_code == "CREDIT_LIMIT_EXCEEDED"
    assert error.value.outstanding == Decimal("500")


def test_paid_and_cancelled_receivables_dont_count():
    paid, cancelled = _owing("400", sale_id=51), _owing("400", sale_id=52)
    paid.balance, paid.status = Decimal("0"), ReceivableStatus.PAID
    cancelled.status = ReceivableStatus.CANCELLED
    credit = customer_credit(
        [credit_customer(credit_limit=Decimal("500"))], receivables=[paid, cancelled]
    )
    sale = _sale(total="500")

    assert credit.open(sale, _pays(sale, credit="500")) is not None


@pytest.mark.parametrize(
    "customer",
    [
        credit_customer(credit_limit=None),
        credit_customer(credit_limit=Decimal("0")),
        credit_customer(is_active=False),
    ],
)
def test_a_customer_without_credit_buys_none(customer):
    credit = customer_credit([customer])
    sale = _sale()
    with pytest.raises(CustomerWithoutCreditError):
        credit.open(sale, _pays(sale))


def test_terms_default_to_zero_days():
    credit = customer_credit([credit_customer(payment_terms=None)])
    sale = _sale()

    receivable = credit.open(sale, _pays(sale))

    assert receivable is not None and receivable.due_on == date.today()


def test_a_refund_goes_to_the_account_first_up_to_its_balance():
    sales = Mock()
    credit = customer_credit(
        [credit_customer()], receivables=[_owing("30", sale_id=1)], sales=sales
    )
    sale = _sale(total="100")

    assert credit.creditable(1, Decimal("50")) == Decimal("30")
    assert credit.credit_refund(sale, refund_id=9, total=Decimal("50")) == Decimal("30")

    receivable = credit.receivables.first(sale_id=1)
    assert (receivable.balance, receivable.status) == (
        Decimal("0"),
        ReceivableStatus.PAID,
    )
    [application] = credit.applications.rows.values()
    assert (application.kind, application.amount, application.refund_id) == (
        ReceivableApplicationKind.REFUND,
        Decimal("30"),
        9,
    )
    assert sale.payment_status == PaymentStatus.PAID
    sales.update.assert_called_once_with(sale)
    # Nothing more to credit
    assert credit.credit_refund(sale, refund_id=10, total=Decimal("5")) == 0


def test_a_sale_without_receivable_credits_nothing():
    credit = customer_credit([credit_customer()])

    assert credit.credit_refund(_sale(), refund_id=9, total=Decimal("50")) == 0
    assert credit.creditable(1, Decimal("50")) == 0


def test_the_receivable_of_a_cancelled_sale_is_cancelled():
    credit = customer_credit([credit_customer()], receivables=[_owing("80", sale_id=1)])

    credit.cancel_for_sale(1)

    assert credit.receivables.first(sale_id=1).status == ReceivableStatus.CANCELLED
    # A sale without one is cancelled as before
    credit.cancel_for_sale(2)


def test_a_sale_with_payments_on_its_account_is_not_cancelled():
    application = ReceivableApplication(
        id=1,
        receivable_id=1,
        amount=Decimal("10"),
        kind=ReceivableApplicationKind.PAYMENT,
        customer_payment_id=1,
    )
    credit = customer_credit(
        [credit_customer()],
        receivables=[_owing("80", sale_id=1)],
        applications=[application],
    )

    with pytest.raises(ReceivableHasPaymentsError):
        credit.cancel_for_sale(1)
