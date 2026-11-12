"""Cuentas por pagar (S5.7): lo que se le debe a un proveedor por sus entregas.

Cada recepción de una orden de compra con un total abre una cuenta por ese
monto, con IVA, que vence según el plazo del proveedor (`payment_terms`, en
días). Su saldo baja con los pagos al proveedor (`SupplierPayment`, aplicados a
una o varias cuentas) y con las devoluciones a proveedor confirmadas.

Estados:

- OPEN: tiene saldo.
- PAID: saldada, por pagos o devoluciones.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from src.payables.domain.exceptions import (
    CreditPaymentNotAllowedError,
    PayableNotOpenError,
)
from src.sales.domain.entities import PaymentMethod
from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import InvalidValueError
from src.shared.domain.money import round_money

ZERO = Decimal("0")


class PayableStatus(StrEnum):
    """Estado de una cuenta por pagar"""

    OPEN = "OPEN"
    PAID = "PAID"


class PayableApplicationKind(StrEnum):
    """Lo que bajó el saldo de una cuenta: un pago o una devolución"""

    PAYMENT = "PAYMENT"
    RETURN = "RETURN"


@dataclass
class Payable(Entity):
    """La cuenta por pagar de una recepción de compra"""

    supplier_id: int
    purchase_order_id: int
    purchase_receipt_id: int
    amount: Decimal
    balance: Decimal
    issued_on: date
    due_on: date
    term_days: int = 0
    # The supplier's invoice for the delivery, when it came with one
    supplier_invoice_number: str | None = None
    status: PayableStatus = PayableStatus.OPEN
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def open(
        cls,
        *,
        supplier_id: int,
        purchase_order_id: int,
        purchase_receipt_id: int,
        amount: Decimal,
        term_days: int,
        issued_on: date,
        supplier_invoice_number: str | None = None,
    ) -> "Payable":
        """La cuenta de lo recibido, que vence en `term_days`"""
        amount = round_money(amount)
        if amount <= ZERO:
            raise InvalidValueError(f"A payable needs a positive amount: {amount}")
        if term_days < 0:
            raise InvalidValueError(f"Payment terms can't be negative: {term_days}")
        return cls(
            supplier_id=supplier_id,
            purchase_order_id=purchase_order_id,
            purchase_receipt_id=purchase_receipt_id,
            amount=amount,
            balance=amount,
            issued_on=issued_on,
            due_on=issued_on + timedelta(days=term_days),
            term_days=term_days,
            supplier_invoice_number=supplier_invoice_number,
        )

    @property
    def is_open(self) -> bool:
        return self.status == PayableStatus.OPEN

    @property
    def paid(self) -> Decimal:
        """Lo que ya bajó de su saldo"""
        return self.amount - self.balance

    def credit(self, amount: Decimal) -> None:
        """Baja su saldo por un pago o una devolución: queda PAID en cero"""
        if not self.is_open:
            raise PayableNotOpenError(self.id)
        amount = round_money(amount)
        if amount <= ZERO or amount > self.balance:
            raise InvalidValueError(
                f"Cannot credit {amount} to payable {self.id} with a balance of "
                f"{self.balance}"
            )
        self.balance -= amount
        if self.balance == ZERO:
            self.status = PayableStatus.PAID

    def days_overdue(self, today: date) -> int:
        """Días desde su vencimiento; cero o menos, todavía no vence"""
        return (today - self.due_on).days


@dataclass
class PayableApplication(Entity):
    """Un pago o una devolución aplicados a una cuenta"""

    payable_id: int
    amount: Decimal
    kind: PayableApplicationKind
    supplier_payment_id: int | None = None
    supplier_return_id: int | None = None
    applied_at: datetime | None = None
    id: int | None = None

    def __post_init__(self):
        if self.applied_at is None:
            self.applied_at = datetime.now()


@dataclass
class SupplierPayment(Entity):
    """Un pago al proveedor, aplicado a una o varias de sus cuentas abiertas"""

    supplier_id: int
    amount: Decimal
    payment_method: PaymentMethod
    number: str | None = None
    reference: str | None = None
    notes: str | None = None
    paid_at: datetime | None = None
    paid_by: str | None = None
    id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self):
        if self.payment_method == PaymentMethod.CREDIT:
            raise CreditPaymentNotAllowedError()
        self.amount = round_money(self.amount)
        if self.amount <= ZERO:
            raise InvalidValueError(
                f"A supplier payment must be positive, got {self.amount}"
            )
        if self.paid_at is None:
            self.paid_at = datetime.now()
