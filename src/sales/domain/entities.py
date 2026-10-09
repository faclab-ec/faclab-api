from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from src.sales.domain.exceptions import InvalidSaleStatusError, SaleNotParkedError
from src.sales.domain.services import discount_factor, tax_breakdown
from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import ValidationError
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
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def ensure_draft(self, operation: str) -> None:
        """Las ventas solo se editan en DRAFT"""
        if self.status != SaleStatus.DRAFT:
            raise InvalidSaleStatusError(self.status, operation)

    def confirm(self) -> None:
        """Confirma la venta (solo si está en DRAFT)"""
        self.ensure_draft("confirm")
        self.status = SaleStatus.CONFIRMED
        if self.sale_date is None:
            self.sale_date = datetime.now()

    def cancel(self) -> None:
        """Cancela la venta (solo si está en DRAFT o CONFIRMED)"""
        if self.status not in (SaleStatus.DRAFT, SaleStatus.CONFIRMED):
            raise InvalidSaleStatusError(self.status, "cancel")
        self.status = SaleStatus.CANCELLED

    @property
    def is_completed(self) -> bool:
        """Confirmada, facturada o no (ver `COMPLETED_SALE_STATUSES`)"""
        return self.status in COMPLETED_SALE_STATUSES

    def invoice(self) -> None:
        """Marca la venta como facturada (solo si está CONFIRMED)"""
        if self.status != SaleStatus.CONFIRMED:
            raise InvalidSaleStatusError(self.status, "invoice")
        self.status = SaleStatus.INVOICED

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


@dataclass
class Payment(Entity):
    """Pago realizado para una venta"""

    sale_id: int
    amount: Decimal
    payment_method: PaymentMethod
    payment_date: datetime | None = None
    reference: str | None = None
    notes: str | None = None
    id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self):
        """Valida que el monto sea positivo"""
        if self.amount <= Decimal("0"):
            raise ValueError(f"Payment amount must be positive, got {self.amount}")
        if self.payment_date is None:
            self.payment_date = datetime.now()
