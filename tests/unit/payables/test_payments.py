"""Payments to suppliers (S5.7): FIFO or by hand, numbered per tenant and
audited"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.organization.domain.numbering import DocumentType
from src.payables.app.commands.payments import (
    RecordSupplierPaymentCommand,
    RecordSupplierPaymentCommandHandler,
)
from src.payables.domain.entities import Payable, PayableApplicationKind, PayableStatus
from src.payables.domain.exceptions import SupplierPaymentExceedsBalanceError
from src.shared.app.audit import AuditAction
from src.shared.domain.exceptions import NotFoundError, ValidationError
from tests.audit import FakeAuditTrail
from tests.payables import (
    InMemoryPayableApplications,
    InMemoryPayables,
    InMemorySupplierPayments,
    InMemorySuppliers,
    supplier,
)


def _payable(id: int, balance: str, due_on: date) -> Payable:
    payable = Payable.open(
        supplier_id=10,
        purchase_order_id=1,
        purchase_receipt_id=100 + id,
        amount=Decimal(balance),
        term_days=0,
        issued_on=due_on,
    )
    payable.id = id
    return payable


class _Handler:
    def __init__(self, *payables: Payable):
        self.payables = InMemoryPayables(payables)
        self.applications = InMemoryPayableApplications()
        self.payments = InMemorySupplierPayments()
        self.numbering = MagicMock()
        self.numbering.next_in_tenant.return_value = "PP-2026-0003"
        self.audit = FakeAuditTrail()
        self.handler = RecordSupplierPaymentCommandHandler(
            InMemorySuppliers([supplier()]),
            self.payables,
            self.applications,
            self.payments,
            self.numbering,
            self.audit,
        )

    def pay(self, **kwargs) -> dict:
        command = RecordSupplierPaymentCommand(
            supplier_id=kwargs.pop("supplier_id", 10),
            amount=kwargs.pop("amount"),
            payment_method=kwargs.pop("payment_method", "TRANSFER"),
            paid_by="Ana",
            **kwargs,
        )
        return self.handler.handle(command)


def test_a_payment_pays_the_one_due_first_then_the_next():
    world = _Handler(
        _payable(1, "30.00", date(2026, 12, 1)), _payable(2, "20.00", date(2026, 11, 1))
    )

    result = world.pay(amount=Decimal("25.00"), reference="TRF-881")

    assert result["number"] == "PP-2026-0003"
    assert world.numbering.next_in_tenant.call_args.args[0] == (
        DocumentType.SUPPLIER_PAYMENT
    )
    assert [
        (a["payable_id"], a["amount"], a["balance"]) for a in result["applications"]
    ] == [
        (2, Decimal("20.00"), Decimal("0.00")),
        (1, Decimal("5.00"), Decimal("25.00")),
    ]
    assert world.payables.rows[2].status == PayableStatus.PAID
    assert {a.kind for a in world.applications.rows.values()} == {
        PayableApplicationKind.PAYMENT
    }
    assert result["paid_by"] == "Ana"
    assert result["supplier_name"] == "Distribuidora Andina"
    assert world.audit.actions == [AuditAction.SUPPLIER_PAYMENT_RECORDED]
    after = world.audit.entries[0].after
    assert after is not None
    assert after["applications"] == [
        {"payable_id": 2, "amount": Decimal("20.00")},
        {"payable_id": 1, "amount": Decimal("5.00")},
    ]


def test_a_payment_by_hand_pays_what_it_says():
    world = _Handler(
        _payable(1, "30.00", date(2026, 12, 1)), _payable(2, "20.00", date(2026, 11, 1))
    )

    result = world.pay(
        amount=Decimal("10.00"),
        applications=[{"payable_id": 1, "amount": Decimal("10.00")}],
    )

    assert [(a["payable_id"], a["amount"]) for a in result["applications"]] == [
        (1, Decimal("10.00"))
    ]
    assert world.payables.rows[2].balance == Decimal("20.00")


def test_a_payment_over_what_is_owed_is_refused_before_numbering():
    world = _Handler(_payable(1, "30.00", date(2026, 12, 1)))

    with pytest.raises(SupplierPaymentExceedsBalanceError):
        world.pay(amount=Decimal("30.01"))
    world.numbering.next_in_tenant.assert_not_called()
    assert world.payments.rows == {}


def test_an_unknown_supplier_or_method_is_refused():
    world = _Handler()
    with pytest.raises(NotFoundError):
        world.pay(supplier_id=99, amount=Decimal("1"))
    with pytest.raises(ValidationError):
        world.pay(amount=Decimal("1"), payment_method="BARTER")
