from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.sales.domain.entities import Payment, SaleItem
from src.shared.domain.events import DomainEvent


def sale_items_data(items: Iterable[SaleItem]) -> list[dict[str, Any]]:
    """Ítems de la venta como los llevan SaleConfirmed y SaleInvoicingRequested"""
    return [
        {
            "product_id": item.product_id,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "discount": item.discount,
            "tax_code": item.tax_code,
            "tax_amount": item.tax_amount,
            "subtotal": item.subtotal,
        }
        for item in items
    ]


def sale_payments_data(payments: Iterable[Payment]) -> list[dict[str, Any]]:
    """Pagos de la venta como los llevan SaleConfirmed y SaleInvoicingRequested"""
    return [{"method": p.payment_method, "amount": p.amount} for p in payments]


@dataclass
class SaleCreated(DomainEvent):
    """Evento emitido cuando se crea una venta"""

    sale_id: int = 0
    customer_id: int | None = None
    total: Decimal = Decimal("0")

    def _payload(self) -> dict[str, Any]:
        return {
            "sale_id": self.sale_id,
            "customer_id": self.customer_id,
            "total": self.total,
        }


@dataclass
class SaleConfirmed(DomainEvent):
    """
    Evento emitido cuando se confirma una venta.
    Este evento desencadena la creación de movimientos de inventario (OUT).
    """

    sale_id: int = 0
    customer_id: int | None = None
    items: list[dict[str, Any]] = field(
        default_factory=list
    )  # [{product_id, quantity, unit_price, discount, tax_code, tax_amount, subtotal}]
    subtotal: Decimal = Decimal("0")
    total_discount: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    payments: list[dict[str, Any]] = field(default_factory=list)  # [{method, amount}]
    source: str = "admin"

    def _payload(self) -> dict[str, Any]:
        return {
            "sale_id": self.sale_id,
            "customer_id": self.customer_id,
            "items": self.items,
            "subtotal": self.subtotal,
            "total_discount": self.total_discount,
            "total": self.total,
            "payments": self.payments,
            "source": self.source,
        }


@dataclass
class SaleInvoicingRequested(DomainEvent):
    """
    Pide facturar de nuevo una venta confirmada: su `sales.confirmed` no llegó a
    faclab-invoicing o el SRI rechazó la factura y ya se corrigieron los datos.
    Lleva lo mismo que SaleConfirmed, pero no mueve inventario.
    """

    sale_id: int = 0
    customer_id: int | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    subtotal: Decimal = Decimal("0")
    total_discount: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    payments: list[dict[str, Any]] = field(default_factory=list)
    source: str = "admin"

    def _payload(self) -> dict[str, Any]:
        return {
            "sale_id": self.sale_id,
            "customer_id": self.customer_id,
            "items": self.items,
            "subtotal": self.subtotal,
            "total_discount": self.total_discount,
            "total": self.total,
            "payments": self.payments,
            "source": self.source,
        }


@dataclass
class SaleCancelled(DomainEvent):
    """
    Evento emitido cuando se cancela una venta.
    Si la venta estaba confirmada, esto desencadena movimientos de reversión (IN).
    """

    sale_id: int = 0
    customer_id: int | None = None
    items: list[dict[str, Any]] = field(
        default_factory=list
    )  # [{product_id, quantity}]
    reason: str = ""
    was_confirmed: bool = (
        False  # True si la venta estaba confirmada antes de cancelarse
    )
    source: str = "admin"

    def _payload(self) -> dict[str, Any]:
        return {
            "sale_id": self.sale_id,
            "customer_id": self.customer_id,
            "items": self.items,
            "reason": self.reason,
            "was_confirmed": self.was_confirmed,
            "source": self.source,
        }


@dataclass
class SaleInvoiced(DomainEvent):
    """Evento emitido cuando el SRI autoriza la factura de una venta"""

    sale_id: int = 0
    customer_id: int | None = None
    invoice_id: str = ""  # id de la factura en faclab-invoicing
    total: Decimal = Decimal("0")

    def _payload(self) -> dict[str, Any]:
        return {
            "sale_id": self.sale_id,
            "customer_id": self.customer_id,
            "invoice_id": self.invoice_id,
            "total": self.total,
        }


@dataclass
class PaymentReceived(DomainEvent):
    """
    Evento emitido cuando se registra un pago para una venta.
    Permite actualizar el estado de pago de la venta.
    """

    payment_id: int = 0
    sale_id: int = 0
    amount: Decimal = Decimal("0")
    payment_method: str = ""
    reference: str = ""

    def _payload(self) -> dict[str, Any]:
        return {
            "payment_id": self.payment_id,
            "sale_id": self.sale_id,
            "amount": self.amount,
            "payment_method": self.payment_method,
            "reference": self.reference,
        }


@dataclass
class SaleItemAdded(DomainEvent):
    """Evento emitido cuando se agrega un item a una venta"""

    sale_id: int = 0
    sale_item_id: int = 0
    product_id: int = 0
    quantity: int = 0
    unit_price: Decimal = Decimal("0")

    def _payload(self) -> dict[str, Any]:
        return {
            "sale_id": self.sale_id,
            "sale_item_id": self.sale_item_id,
            "product_id": self.product_id,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
        }


@dataclass
class SaleItemRemoved(DomainEvent):
    """Evento emitido cuando se elimina un item de una venta"""

    sale_id: int = 0
    sale_item_id: int = 0
    product_id: int = 0
    quantity: int = 0

    def _payload(self) -> dict[str, Any]:
        return {
            "sale_id": self.sale_id,
            "sale_item_id": self.sale_item_id,
            "product_id": self.product_id,
            "quantity": self.quantity,
        }
