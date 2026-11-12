"""SupplierAccounts (S5.7): the payable of a receipt and the credit of a
return, inside their transactions"""

from datetime import date
from decimal import Decimal

from src.payables.domain.entities import Payable, PayableApplicationKind, PayableStatus
from tests.payables import supplier, supplier_accounts


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


def test_a_receipt_opens_a_payable_due_in_the_suppliers_terms():
    accounts, payables, _ = supplier_accounts(suppliers=[supplier(payment_terms=15)])

    payable = accounts.open_for_receipt(
        supplier_id=10,
        purchase_order_id=1,
        purchase_receipt_id=4,
        amount=Decimal("14.38"),
        issued_on=date(2026, 11, 3),
        supplier_invoice_number="001-002-000000123",
    )

    assert payable is not None
    assert (payable.amount, payable.due_on, payable.term_days) == (
        Decimal("14.38"),
        date(2026, 11, 18),
        15,
    )
    assert payable.supplier_invoice_number == "001-002-000000123"
    assert len(payables.rows) == 1


def test_a_supplier_without_terms_is_due_the_same_day():
    accounts, _, _ = supplier_accounts(suppliers=[supplier(payment_terms=None)])

    payable = accounts.open_for_receipt(
        supplier_id=10,
        purchase_order_id=1,
        purchase_receipt_id=4,
        amount=Decimal("1.00"),
        issued_on=date(2026, 11, 3),
    )

    assert payable is not None and payable.due_on == date(2026, 11, 3)


def test_a_receipt_without_cost_owes_nothing():
    accounts, payables, _ = supplier_accounts()

    assert (
        accounts.open_for_receipt(
            supplier_id=10,
            purchase_order_id=1,
            purchase_receipt_id=4,
            amount=Decimal("0"),
            issued_on=date(2026, 11, 3),
        )
        is None
    )
    assert payables.rows == {}


def test_a_return_credits_what_is_owed_and_says_how_much():
    accounts, payables, applications = supplier_accounts(
        _payable(1, "10.00", date(2026, 10, 1), order=1),
        _payable(2, "15.00", date(2026, 11, 1), order=2),
    )

    credited = accounts.credit_return(
        supplier_id=10, purchase_order_id=2, supplier_return_id=3, amount=Decimal("40")
    )

    assert credited == Decimal("25.00")
    assert payables.locked == [{"supplier_id": 10}]
    assert {p.id: p.status for p in payables.rows.values()} == {
        1: PayableStatus.PAID,
        2: PayableStatus.PAID,
    }
    assert [
        (a.payable_id, a.amount, a.kind, a.supplier_return_id)
        for a in applications.rows.values()
    ] == [
        (2, Decimal("15.00"), PayableApplicationKind.RETURN, 3),
        (1, Decimal("10.00"), PayableApplicationKind.RETURN, 3),
    ]


def test_a_return_to_a_supplier_already_paid_credits_nothing():
    accounts, _, applications = supplier_accounts()

    credited = accounts.credit_return(
        supplier_id=10, purchase_order_id=1, supplier_return_id=3, amount=Decimal("9")
    )

    assert credited == Decimal("0")
    assert applications.rows == {}
