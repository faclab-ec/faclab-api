"""Abonos de clientes (S5.5): FIFO o manual, en la caja de un turno o fuera de
ella, con la venta pagada cuando su cuenta se salda"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.organization.domain.numbering import DocumentType
from src.pos.shift.domain.entities import Shift
from src.pos.shift.domain.exceptions import NoOpenShiftError
from src.receivables.app.commands.payments import (
    RecordCustomerPaymentCommand,
    RecordCustomerPaymentCommandHandler,
)
from src.receivables.domain.entities import (
    Receivable,
    ReceivableApplicationKind,
    ReceivableStatus,
)
from src.receivables.domain.exceptions import (
    CreditPaymentNotAllowedError,
    CustomerPaymentExceedsBalanceError,
)
from src.sales.domain.entities import PaymentStatus, Sale
from src.shared.app.audit import AuditAction
from src.shared.domain.exceptions import NotFoundError
from tests.audit import FakeAuditTrail
from tests.receivables import (
    InMemoryApplications,
    InMemoryCustomerPayments,
    InMemoryCustomers,
    InMemoryReceivables,
    credit_customer,
)
from tests.unit.pos.terminals import AT_TERMINAL, TERMINAL, terminal_resolver


def _receivable(id: int, balance: str, due_in: int) -> Receivable:
    receivable = Receivable.open(
        customer_id=7,
        sale_id=100 + id,
        amount=Decimal(balance),
        term_days=30,
        issued_on=date.today() + timedelta(days=due_in - 30),
    )
    receivable.id = id
    return receivable


class _Handler:
    def __init__(self, *receivables: Receivable, shift: Shift | None = None):
        self.customers = InMemoryCustomers([credit_customer()])
        self.receivables = InMemoryReceivables(receivables)
        self.applications = InMemoryApplications()
        self.payments = InMemoryCustomerPayments()
        self.sales = MagicMock()
        self.sales.get_by_ids.side_effect = lambda ids: [
            Sale(id=i, customer_id=7, total=Decimal("100"), number=f"V-001-{i:06d}")
            for i in ids
        ]
        self.shifts = MagicMock()
        self.shifts.first.return_value = shift
        self.numbering = MagicMock()
        self.numbering.next_in_tenant.return_value = "AB-2026-0001"
        self.audit = FakeAuditTrail()
        self.handler = RecordCustomerPaymentCommandHandler(
            self.customers,
            self.receivables,
            self.applications,
            self.payments,
            self.sales,
            terminal_resolver(),
            self.shifts,
            self.numbering,
            self.audit,
        )

    def pay(self, amount: str, method: str = "CASH", **kwargs) -> dict:
        return self.handler.handle(
            RecordCustomerPaymentCommand(
                customer_id=7,
                amount=Decimal(amount),
                payment_method=method,
                received_by="Ana",
                **kwargs,
            )
        )


def test_a_payment_goes_to_the_receivable_due_first():
    payments = _Handler(
        _receivable(1, "50", due_in=10), _receivable(2, "30", due_in=-5)
    )

    result = payments.pay("40")

    assert [
        (a["receivable_id"], a["amount"], a["balance"]) for a in result["applications"]
    ] == [
        (2, Decimal("30"), Decimal("0")),
        (1, Decimal("10"), Decimal("40")),
    ]
    assert payments.receivables.get_by_id(2).status == ReceivableStatus.PAID
    assert payments.receivables.get_by_id(1).balance == Decimal("40")
    assert {a.kind for a in payments.applications.rows.values()} == {
        ReceivableApplicationKind.PAYMENT
    }
    assert result["number"] == "AB-2026-0001"
    assert result["received_by"] == "Ana"
    assert result["shift_id"] is None
    payments.numbering.next_in_tenant.assert_called_once_with(
        DocumentType.CUSTOMER_PAYMENT, date.today().year
    )
    # The customer first, then its receivables: like a sale on credit
    assert payments.customers.locked == [{"id": 7}]
    assert payments.receivables.locked == [{"customer_id": 7}]


def test_a_manual_payment_pays_what_it_says():
    payments = _Handler(
        _receivable(1, "50", due_in=-10), _receivable(2, "30", due_in=5)
    )

    result = payments.pay(
        "30", applications=[{"receivable_id": 2, "amount": Decimal("30")}]
    )

    assert [(a["receivable_id"], a["amount"]) for a in result["applications"]] == [
        (2, Decimal("30"))
    ]
    assert payments.receivables.get_by_id(1).balance == Decimal("50")


def test_the_sale_is_paid_when_its_receivable_is():
    payments = _Handler(_receivable(1, "50", due_in=0))
    updated: list[Sale] = []
    payments.sales.update.side_effect = updated.append

    payments.pay("50")

    [sale] = updated
    assert sale.id == 101 and sale.payment_status == PaymentStatus.PAID


def test_a_payment_cant_exceed_what_the_customer_owes():
    payments = _Handler(_receivable(1, "50", due_in=0))

    with pytest.raises(CustomerPaymentExceedsBalanceError):
        payments.pay("50.01")
    assert payments.payments.rows == {}


def test_a_payment_on_account_is_not_made_on_credit():
    with pytest.raises(CreditPaymentNotAllowedError):
        _Handler(_receivable(1, "50", due_in=0)).pay("10", method="CREDIT")


def test_another_customer_is_not_found():
    payments = _Handler()
    with pytest.raises(NotFoundError):
        payments.handler.handle(
            RecordCustomerPaymentCommand(
                customer_id=99, amount=Decimal("1"), payment_method="CASH"
            )
        )


def test_at_the_pos_it_goes_to_the_terminals_open_shift():
    shift = Shift(id=12, terminal_id=TERMINAL.id, branch_id=1, cashier_name="Ana")
    payments = _Handler(_receivable(1, "50", due_in=0), shift=shift)

    result = payments.pay("20", terminal=AT_TERMINAL)

    assert (result["shift_id"], result["terminal_id"], result["branch_id"]) == (
        12,
        TERMINAL.id,
        TERMINAL.branch_id,
    )
    payments.shifts.first.assert_called_once_with(
        terminal_id=TERMINAL.id, status="OPEN"
    )
    [entry] = payments.audit.entries
    assert entry.action == AuditAction.CUSTOMER_PAYMENT_RECORDED
    assert entry.branch_id == TERMINAL.branch_id
    assert entry.after is not None and entry.after["shift_id"] == 12


def test_at_the_pos_it_needs_an_open_shift():
    with pytest.raises(NoOpenShiftError):
        _Handler(_receivable(1, "50", due_in=0)).pay("20", terminal=AT_TERMINAL)
