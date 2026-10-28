from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from src.sales.domain.exceptions import (
    CreditNoteRequiredError,
    InsufficientPaymentError,
    InvalidSaleStatusError,
    InvoiceInProgressError,
    PaymentExceedsBalanceError,
    SaleNotParkedError,
    SaleNotPayableError,
)
from src.sales.domain.services import discount_factor, tax_breakdown
from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import InvalidValueError, ValidationError
from src.shared.domain.money import round_money
from src.shared.domain.tax import TaxCode


class SaleStatus(StrEnum):
    """Estado de una venta"""

    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


# Ventas cerradas, facturadas o no: cuentan en la caja y en los reportes y
# admiten devoluciones. faclab-invoicing pasa una venta a INVOICED cuando el SRI
# autoriza su factura.
COMPLETED_SALE_STATUSES = (SaleStatus.CONFIRMED.value, SaleStatus.INVOICED.value)


class PaymentStatus(StrEnum):
    """Estado de pago de una venta"""

    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    PAID = "PAID"


class InvoiceStatus(StrEnum):
    """Factura de la venta en faclab-invoicing; sin valor, no se envió.

    PENDING desde que su `sales.confirmed` llega al outbox (al confirmar o
    reenviar), REJECTED cuando el SRI la rechaza (con el motivo) y AUTHORIZED
    cuando la autoriza (la venta pasa a INVOICED).
    """

    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"


class PaymentMethod(StrEnum):
    """Método de pago"""

    CASH = "CASH"
    CREDIT_CARD = "CREDIT_CARD"
    DEBIT_CARD = "DEBIT_CARD"
    TRANSFER = "TRANSFER"
    OTHER = "OTHER"


@dataclass
class SaleItem(Entity):
    """Item individual de una venta"""

    sale_id: int
    product_id: int
    quantity: int
    unit_price: Decimal
    discount: Decimal = Decimal("0")
    tax_code: TaxCode = TaxCode.VAT_15
    tax_amount: Decimal = Decimal("0")
    price_override: Decimal | None = None
    override_reason: str | None = None
    id: int | None = None

    @property
    def subtotal(self) -> Decimal:
        """Calcula el subtotal del item (cantidad * precio - descuento)"""
        base = self.unit_price * self.quantity
        discount_amount = base * (self.discount / Decimal("100"))
        return base - discount_amount

    def recalculate_tax(self) -> None:
        """IVA del item a precisión completa, antes del descuento global de la venta"""
        self.tax_amount = self.subtotal * self.tax_code.rate / Decimal("100")


@dataclass
class Sale(Entity):
    """Venta del sistema"""

    customer_id: int | None = None
    is_final_consumer: bool = False
    shift_id: int | None = None
    # Where the sale is made, copied from its POS terminal; null in sales
    # from before S2.6
    branch_id: int | None = None
    emission_point_id: int | None = None
    terminal_id: int | None = None
    # Correlative per branch (`V-001-000123`), given when it is confirmed
    number: str | None = None
    status: SaleStatus = SaleStatus.DRAFT
    sale_date: datetime | None = None
    subtotal: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    discount: Decimal = Decimal("0")
    discount_type: str | None = None
    discount_value: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    payment_status: PaymentStatus = PaymentStatus.PENDING
    notes: str | None = None
    created_by: str | None = None
    parked_at: datetime | None = None
    park_reason: str | None = None
    invoice_status: InvoiceStatus | None = None
    # The last invoice faclab-invoicing reported a result for (authorized or
    # rejected), and why the SRI rejected it
    invoice_id: str | None = None
    invoice_rejection_reason: str | None = None
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def ensure_draft(self, operation: str) -> None:
        """Las ventas solo se editan en DRAFT"""
        if self.status != SaleStatus.DRAFT:
            raise InvalidSaleStatusError(self.status, operation)

    def confirm(self, number: str | None = None) -> None:
        """Confirma la venta (solo si está en DRAFT y pagada, ver `settle`) con
        su número de documento. Las ventas a crédito llegan en S5.5."""
        self.ensure_draft("confirm")
        if self.payment_status != PaymentStatus.PAID:
            raise InsufficientPaymentError(self.id, self.total, Decimal("0"))
        self.status = SaleStatus.CONFIRMED
        if number is not None:
            self.number = number
        if self.sale_date is None:
            self.sale_date = datetime.now()

    def cancel(self) -> None:
        """Cancela la venta (solo si está en DRAFT o CONFIRMED).

        Una confirmada no se cancela mientras su factura espera al SRI, y una
        facturada solo se anula con nota de crédito (S4.5).
        """
        if self.status == SaleStatus.INVOICED:
            raise CreditNoteRequiredError(self.id)
        if self.status not in (SaleStatus.DRAFT, SaleStatus.CONFIRMED):
            raise InvalidSaleStatusError(self.status, "cancel")
        if self.invoice_status == InvoiceStatus.PENDING:
            raise InvoiceInProgressError(self.id)
        self.status = SaleStatus.CANCELLED

    @property
    def is_completed(self) -> bool:
        """Confirmada, facturada o no (ver `COMPLETED_SALE_STATUSES`)"""
        return self.status in COMPLETED_SALE_STATUSES

    def await_invoice(self) -> None:
        """La venta se envió a faclab-invoicing (al confirmarla o reenviarla).
        Conserva el id de la factura rechazada: así se reconoce un rechazo
        repetido de esa factura (ver `reject_invoice`)."""
        if self.status != SaleStatus.CONFIRMED:
            raise InvalidSaleStatusError(self.status, "invoice")
        self.invoice_status = InvoiceStatus.PENDING
        self.invoice_rejection_reason = None

    def reject_invoice(self, invoice_id: str, reason: str | None = None) -> bool:
        """El SRI rechazó la factura: la venta se puede corregir y reenviar o
        cancelar. Solo cambia una factura pendiente, y no por un rechazo de la
        factura que ya se rechazó (un mensaje repetido que llega después del
        reenvío); dice si cambió."""
        if self.invoice_status != InvoiceStatus.PENDING:
            return False
        if invoice_id == self.invoice_id:
            return False
        self.invoice_status = InvoiceStatus.REJECTED
        self.invoice_id = invoice_id
        self.invoice_rejection_reason = reason[:1000] if reason else None
        return True

    def invoice(self, invoice_id: str | None = None) -> None:
        """Marca la venta como facturada (solo si está CONFIRMED) con la
        factura que autorizó el SRI"""
        if self.status != SaleStatus.CONFIRMED:
            raise InvalidSaleStatusError(self.status, "invoice")
        self.status = SaleStatus.INVOICED
        self.invoice_status = InvoiceStatus.AUTHORIZED
        if invoice_id is not None:
            self.invoice_id = invoice_id
        self.invoice_rejection_reason = None

    def park(self, reason: str | None = None) -> None:
        """Aparca la venta para retomarla después (solo si está en DRAFT)"""
        self.ensure_draft("park")
        self.parked_at = datetime.now()
        self.park_reason = reason

    def resume(self) -> None:
        """Retoma una venta aparcada"""
        if self.parked_at is None:
            raise SaleNotParkedError(self.id)
        self.parked_at = None
        self.park_reason = None

    def apply_discount(self, discount_type: str, discount_value: Decimal) -> None:
        """Aplica un descuento global (solo en DRAFT); luego hay que recalcular los totales"""
        self.ensure_draft("apply discount to")
        if discount_type not in ("PERCENTAGE", "AMOUNT"):
            raise ValidationError(
                f"Invalid discount_type: {discount_type}. Must be PERCENTAGE or AMOUNT"
            )
        if discount_value < Decimal("0"):
            raise ValidationError("discount_value must be non-negative")
        if discount_type == "PERCENTAGE" and discount_value > Decimal("100"):
            raise ValidationError("Percentage discount cannot exceed 100")
        self.discount_type = discount_type
        self.discount_value = discount_value

    def recalculate_totals(self, items: Iterable[SaleItem]) -> None:
        """Recalcula subtotal, descuento, IVA y total a partir de los items.

        Los montos de la venta se redondean a centavos y el total es exactamente
        subtotal - descuento + IVA. El descuento global se prorratea sobre la base
        de cada item antes de calcular el IVA (ver `tax_breakdown`).
        """
        items = list(items)
        subtotal = round_money(sum((item.subtotal for item in items), Decimal("0")))

        if self.discount_type == "PERCENTAGE":
            discount = round_money(subtotal * self.discount_value / Decimal("100"))
        elif self.discount_type == "AMOUNT":
            discount = min(round_money(self.discount_value), subtotal)
        else:
            discount = Decimal("0")

        breakdown = tax_breakdown(
            ((item.tax_code, item.subtotal, item.tax_amount) for item in items),
            discount_factor(subtotal, discount),
        )
        self.subtotal = subtotal
        self.discount = discount
        self.tax = sum((tax for _, tax in breakdown.values()), Decimal("0"))
        self.total = subtotal - discount + self.tax

    def is_covered_by(self, amount: Decimal) -> bool:
        """Indica si el monto cubre el total, comparando al centavo"""
        return round_money(amount) >= round_money(self.total)

    def update_payment_status(self, total_paid: Decimal) -> None:
        """Actualiza el estado de pago basándose en el monto pagado"""
        if total_paid <= Decimal("0"):
            self.payment_status = PaymentStatus.PENDING
        elif self.is_covered_by(total_paid):
            self.payment_status = PaymentStatus.PAID
        else:
            self.payment_status = PaymentStatus.PARTIAL

    def balance(self, payments: Iterable["Payment"]) -> Decimal:
        """Lo que falta pagar del total después de lo aplicado por los pagos"""
        paid = sum((payment.amount for payment in payments), Decimal("0"))
        return round_money(self.total) - paid

    def take_payment(self, payment: "Payment", previous: Iterable["Payment"]) -> None:
        """Aplica un pago nuevo a lo que falta pagar, después de los anteriores.

        Una venta cancelada o facturada no recibe pagos.
        """
        if self.status in (SaleStatus.CANCELLED, SaleStatus.INVOICED):
            raise SaleNotPayableError(self.id, self.status)
        previous = list(previous)
        payment.apply(self.balance(previous))
        self.update_payment_status(sum((p.amount for p in previous), payment.amount))

    def settle(self, payments: Iterable["Payment"]) -> None:
        """Aplica los pagos, en orden, al total de la venta.

        Cada pago toma lo que todavía falta y el resto de uno en efectivo es el
        vuelto, así que lo aplicado suma exactamente el total. Se vuelve a
        calcular al confirmar porque los ítems de un borrador cambian después de
        cobrar. Falla si los pagos no cubren el total.
        """
        owed = round_money(self.total)
        paid = Decimal("0")
        for payment in payments:
            payment.apply(owed - paid)
            paid += payment.amount
        if paid < owed:
            raise InsufficientPaymentError(self.id, owed, paid)
        self.payment_status = PaymentStatus.PAID


@dataclass
class Payment(Entity):
    """Pago de una venta: lo que entrega el cliente, lo que se aplica y el vuelto"""

    sale_id: int
    # Applied to the sale: what counts in its balance, in the cash register
    # and in the invoice's `pagos`
    amount: Decimal
    payment_method: PaymentMethod
    payment_date: datetime | None = None
    reference: str | None = None
    notes: str | None = None
    # What the customer handed over, to the cent: amount + change
    amount_tendered: Decimal | None = None
    # Given back from a cash payment that exceeds what the sale owed
    change: Decimal = Decimal("0")
    id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self):
        """Valida que lo entregado sea positivo; por defecto es el monto más el vuelto.

        Lo aplicado puede ser cero solo en un pago anterior a S3.3 que la
        migración dejó entero como vuelto; `apply` no lo permite en uno nuevo.
        """
        if self.amount_tendered is None:
            self.amount_tendered = self.amount + self.change
        if self.amount_tendered <= Decimal("0"):
            raise InvalidValueError(
                f"Payment amount must be positive, got {self.amount_tendered}"
            )
        if self.amount < Decimal("0") or self.change < Decimal("0"):
            raise InvalidValueError(
                f"Payment amount and change can't be negative, got "
                f"{self.amount} and {self.change}"
            )
        self.amount_tendered = round_money(self.amount_tendered)
        if self.payment_date is None:
            self.payment_date = datetime.now()

    def apply(self, owed: Decimal) -> None:
        """Aplica a la venta lo que todavía debe, tomado de lo entregado.

        El resto de un pago en efectivo es el vuelto; otro medio de pago no
        puede pasarse de lo que se debe, y un pago que no aplica nada sobra.
        """
        tendered = self.amount_tendered or self.amount
        applied = min(tendered, round_money(owed))
        change = tendered - applied
        if applied <= Decimal("0") or (
            change > Decimal("0") and self.payment_method != PaymentMethod.CASH
        ):
            raise PaymentExceedsBalanceError(
                tendered, max(owed, Decimal("0")), self.payment_method
            )
        self.amount = applied
        self.change = change
