"""Cuentas por cobrar (S5.5): lo que un cliente debe de sus ventas a crédito.

Una venta confirmada en el POS con un pago CREDIT abre una cuenta por ese monto,
con vencimiento según el plazo del cliente (`payment_terms`, en días). Su saldo
baja con los abonos (`CustomerPayment`, aplicados a una o varias cuentas) y con
las devoluciones de la venta, que se acreditan primero a la cuenta.

Estados:

- OPEN: tiene saldo.
- PAID: saldada, por abonos o devoluciones.
- CANCELLED: su venta se anuló antes de recibir abonos.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from src.receivables.domain.exceptions import (
    CreditPaymentNotAllowedError,
    ReceivableHasPaymentsError,
    ReceivableNotOpenError,
)
from src.sales.domain.entities import PaymentMethod
from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import InvalidValueError
from src.shared.domain.money import round_money


class ReceivableStatus(StrEnum):
    """Estado de una cuenta por cobrar"""

    OPEN = "OPEN"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class ReceivableApplicationKind(StrEnum):
    """Lo que bajó el saldo de una cuenta: un abono o una devolución"""

    PAYMENT = "PAYMENT"
    REFUND = "REFUND"


@dataclass
class Receivable(Entity):
    """La cuenta por cobrar de una venta a crédito"""

    customer_id: int
    sale_id: int
    amount: Decimal
    balance: Decimal
    issued_on: date
    due_on: date
    term_days: int = 0
    branch_id: int | None = None
    status: ReceivableStatus = ReceivableStatus.OPEN
    cancelled_at: datetime | None = None
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def open(
        cls,
        *,
        customer_id: int,
        sale_id: int,
        amount: Decimal,
        term_days: int,
        issued_on: date,
        branch_id: int | None = None,
    ) -> "Receivable":
        """La cuenta de lo que quedó a crédito, que vence en `term_days`"""
        amount = round_money(amount)
        if amount <= Decimal("0"):
            raise InvalidValueError(f"A receivable needs a positive amount: {amount}")
        if term_days < 0:
            raise InvalidValueError(f"Payment terms can't be negative: {term_days}")
        return cls(
            customer_id=customer_id,
            sale_id=sale_id,
            amount=amount,
            balance=amount,
            issued_on=issued_on,
            due_on=issued_on + timedelta(days=term_days),
            term_days=term_days,
            branch_id=branch_id,
        )

    @property
    def is_open(self) -> bool:
        return self.status == ReceivableStatus.OPEN

    @property
    def collected(self) -> Decimal:
        """Lo que ya bajó de su saldo"""
        return self.amount - self.balance

    def credit(self, amount: Decimal) -> None:
        """Baja su saldo por un abono o una devolución: queda PAID en cero"""
        if not self.is_open:
            raise ReceivableNotOpenError(self.id)
        amount = round_money(amount)
        if amount <= Decimal("0") or amount > self.balance:
            raise InvalidValueError(
                f"Cannot credit {amount} to receivable {self.id} with a balance of "
                f"{self.balance}"
            )
        self.balance -= amount
        if self.balance == Decimal("0"):
            self.status = ReceivableStatus.PAID

    def cancel(self, has_applications: bool) -> None:
        """Su venta se anuló: solo si nada bajó su saldo todavía"""
        if not self.is_open or has_applications:
            raise ReceivableHasPaymentsError(self.sale_id)
        self.status = ReceivableStatus.CANCELLED
        self.balance = Decimal("0")
        self.cancelled_at = datetime.now()

    def days_overdue(self, today: date) -> int:
        """Días desde su vencimiento; cero o menos, todavía no vence"""
        return (today - self.due_on).days


@dataclass
class ReceivableApplication(Entity):
    """Un abono o una devolución aplicados a una cuenta"""

    receivable_id: int
    amount: Decimal
    kind: ReceivableApplicationKind
    customer_payment_id: int | None = None
    refund_id: int | None = None
    applied_at: datetime | None = None
    id: int | None = None

    def __post_init__(self):
        if self.applied_at is None:
            self.applied_at = datetime.now()


@dataclass
class CustomerPayment(Entity):
    """Un abono del cliente: en la caja de un turno o fuera de ella, aplicado a
    una o varias de sus cuentas abiertas"""

    customer_id: int
    amount: Decimal
    payment_method: PaymentMethod
    number: str | None = None
    reference: str | None = None
    notes: str | None = None
    paid_at: datetime | None = None
    received_by: str | None = None
    # Where it was received: the terminal and its open shift at the POS (a
    # cash payment counts in that shift's cash), or only a branch outside it
    branch_id: int | None = None
    terminal_id: int | None = None
    shift_id: int | None = None
    id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self):
        if self.payment_method == PaymentMethod.CREDIT:
            raise CreditPaymentNotAllowedError()
        self.amount = round_money(self.amount)
        if self.amount <= Decimal("0"):
            raise InvalidValueError(
                f"A payment on account must be positive, got {self.amount}"
            )
        if self.paid_at is None:
            self.paid_at = datetime.now()
