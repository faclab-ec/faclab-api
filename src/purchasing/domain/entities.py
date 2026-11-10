from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from src.purchasing.domain.exceptions import (
    ExceedsPendingQuantityError,
    InvalidPurchaseOrderStatusError,
)
from src.shared.domain.entities import Entity
from src.shared.domain.money import round_money


class PurchaseOrderStatus(StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    PARTIAL = "partial"
    RECEIVED = "received"
    CANCELLED = "cancelled"


@dataclass
class PurchaseOrder(Entity):
    supplier_id: int
    order_number: str
    id: int | None = None
    status: PurchaseOrderStatus = PurchaseOrderStatus.DRAFT
    subtotal: Decimal = Decimal("0.00")
    tax: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    notes: str | None = None
    expected_date: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def ensure_draft(self, operation: str) -> None:
        if self.status != PurchaseOrderStatus.DRAFT:
            raise InvalidPurchaseOrderStatusError(self.status, operation)

    def update_details(
        self, supplier_id: int, notes: str | None, expected_date: datetime | None
    ) -> None:
        self.ensure_draft("update")
        self.supplier_id = supplier_id
        self.notes = notes
        self.expected_date = expected_date

    def send(self) -> None:
        self.ensure_draft("send")
        self.status = PurchaseOrderStatus.SENT

    def cancel(self) -> None:
        if self.status in (PurchaseOrderStatus.RECEIVED, PurchaseOrderStatus.CANCELLED):
            raise InvalidPurchaseOrderStatusError(self.status, "cancel")
        self.status = PurchaseOrderStatus.CANCELLED

    def ensure_receivable(self) -> None:
        if self.status not in (PurchaseOrderStatus.SENT, PurchaseOrderStatus.PARTIAL):
            raise InvalidPurchaseOrderStatusError(self.status, "receive")

    def recalculate_totals(self, items: list["PurchaseOrderItem"]) -> None:
        """Totales redondeados a centavos; las líneas guardan su costo completo"""
        self.subtotal = round_money(
            sum((item.subtotal for item in items), Decimal("0.00"))
        )
        self.tax = Decimal("0.00")
        self.total = self.subtotal + self.tax

    def update_reception_status(self, items: list["PurchaseOrderItem"]) -> None:
        """Pasa a RECEIVED cuando no queda nada pendiente; si no, a PARTIAL"""
        self.ensure_receivable()
        if all(item.quantity_pending == 0 for item in items):
            self.status = PurchaseOrderStatus.RECEIVED
        else:
            self.status = PurchaseOrderStatus.PARTIAL


@dataclass
class PurchaseOrderItem(Entity):
    """Una línea de la orden, en una presentación del producto (S5.2): lo
    pedido, lo recibido y lo pendiente se cuentan en ella (2 cajas) y
    `unit_cost` es de una de ellas; `unit_factor` las convierte a unidades base"""

    purchase_order_id: int
    product_id: int
    quantity_ordered: Decimal
    unit_cost: Decimal
    id: int | None = None
    quantity_received: Decimal = Decimal(0)
    # Its presentation (null before S5.2: the base unit) and its factor
    presentation_id: int | None = None
    unit_factor: Decimal = Decimal(1)

    @property
    def quantity_pending(self) -> Decimal:
        return self.quantity_ordered - self.quantity_received

    @property
    def subtotal(self) -> Decimal:
        return self.unit_cost * self.quantity_ordered

    def update(self, quantity_ordered: Decimal, unit_cost: Decimal) -> None:
        self.quantity_ordered = quantity_ordered
        self.unit_cost = unit_cost

    def receive(self, quantity: Decimal) -> None:
        """Registra unidades recibidas sin superar lo pendiente"""
        if quantity > self.quantity_pending:
            raise ExceedsPendingQuantityError(
                self.require_id(), quantity, self.quantity_pending
            )
        self.quantity_received += quantity


@dataclass
class PurchaseReceipt(Entity):
    purchase_order_id: int
    id: int | None = None
    notes: str | None = None
    received_at: datetime | None = None
    created_at: datetime | None = None


@dataclass
class PurchaseReceiptItem(Entity):
    """Lo recibido de una línea, en su presentación; `base_quantity` es lo que
    entra al stock (S5.2)"""

    purchase_receipt_id: int
    purchase_order_item_id: int
    product_id: int
    quantity_received: Decimal
    id: int | None = None
    location_id: int | None = None
    lot_number: str | None = None
    serial_numbers: list[str] | None = None
    unit_factor: Decimal = Decimal(1)

    @property
    def base_quantity(self) -> Decimal:
        return self.quantity_received * self.unit_factor
