from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from src.purchasing.domain.exceptions import (
    EmptySupplierReturnError,
    ExceedsPendingQuantityError,
    ExceedsReturnableQuantityError,
    InvalidPurchaseOrderStatusError,
    InvalidSupplierReturnStatusError,
    SupplierReturnCreditExceedsTotalError,
)
from src.sales.domain.services import TaxedLine, tax_breakdown
from src.shared.domain.entities import Entity
from src.shared.domain.money import round_cost, round_money
from src.shared.domain.tax import TaxCode

ZERO = Decimal("0")


def taxed_line(tax_code: TaxCode, unit_cost: Decimal, quantity: Decimal) -> TaxedLine:
    """Una línea de compra a precisión completa: su tarifa, su base y su IVA"""
    subtotal = unit_cost * quantity
    return tax_code, subtotal, subtotal * tax_code.rate / Decimal("100")


def purchase_tax_breakdown(
    lines: Iterable[TaxedLine],
) -> dict[TaxCode, tuple[Decimal, Decimal]]:
    """Base imponible e IVA por tarifa, a centavos (S5.7). Es el cálculo de
    ventas sin descuento global: cada grupo se redondea, como los subtotales
    por tarifa de la factura del proveedor"""
    return tax_breakdown(lines, Decimal("1"))


def purchase_totals(lines: Iterable[TaxedLine]) -> tuple[Decimal, Decimal, Decimal]:
    """(subtotal, IVA, total) de un documento de compra: el subtotal a
    centavos y el IVA como la suma de los grupos por tarifa ya redondeados"""
    lines = list(lines)
    subtotal = round_money(sum((line[1] for line in lines), ZERO))
    breakdown = purchase_tax_breakdown(lines)
    tax = sum((tax for _, tax in breakdown.values()), ZERO)
    return subtotal, tax, subtotal + tax


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

    def recalculate_totals(self, items: Iterable["PurchaseOrderItem"]) -> None:
        """Totales a centavos con el IVA de cada línea por su tarifa (S5.7); las
        líneas guardan su costo y su IVA completos"""
        self.subtotal, self.tax, self.total = purchase_totals(
            item.taxed_line() for item in items
        )

    @staticmethod
    def tax_breakdown(
        items: Iterable["PurchaseOrderItem"],
    ) -> dict[TaxCode, tuple[Decimal, Decimal]]:
        """Base imponible e IVA por tarifa, a centavos"""
        return purchase_tax_breakdown(item.taxed_line() for item in items)

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
    # The product's VAT when the line was added and the line's VAT at full
    # precision (S5.7); the cost never includes it
    tax_code: TaxCode = TaxCode.VAT_15
    tax_amount: Decimal = ZERO
    # What went back to the supplier, in the line's presentation (S5.7)
    quantity_returned: Decimal = ZERO

    @property
    def quantity_pending(self) -> Decimal:
        return self.quantity_ordered - self.quantity_received

    @property
    def quantity_returnable(self) -> Decimal:
        """Lo recibido que todavía no volvió al proveedor"""
        return self.quantity_received - self.quantity_returned

    @property
    def subtotal(self) -> Decimal:
        return self.unit_cost * self.quantity_ordered

    @property
    def base_unit_cost(self) -> Decimal:
        """El costo de una unidad base (S5.6): una caja de 12 a 30,00 pone
        cada unidad a 2,50. Es lo que la recepción lleva al stock"""
        return round_cost(self.unit_cost / self.unit_factor)

    def recalculate_tax(self) -> None:
        self.tax_amount = taxed_line(
            self.tax_code, self.unit_cost, self.quantity_ordered
        )[2]

    def taxed_line(self, quantity: Decimal | None = None) -> TaxedLine:
        """La línea pedida o, con `quantity`, una parte de ella (lo recibido)
        al mismo costo y tarifa"""
        if quantity is None:
            return self.tax_code, self.subtotal, self.tax_amount
        return taxed_line(self.tax_code, self.unit_cost, quantity)

    def update(self, quantity_ordered: Decimal, unit_cost: Decimal) -> None:
        self.quantity_ordered = quantity_ordered
        self.unit_cost = unit_cost
        self.recalculate_tax()

    def receive(self, quantity: Decimal) -> None:
        """Registra unidades recibidas sin superar lo pendiente"""
        if quantity > self.quantity_pending:
            raise ExceedsPendingQuantityError(
                self.require_id(), quantity, self.quantity_pending
            )
        self.quantity_received += quantity

    def return_goods(self, quantity: Decimal) -> None:
        """Registra unidades devueltas al proveedor sin superar lo recibido
        menos lo ya devuelto (S5.7)"""
        if quantity > self.quantity_returnable:
            raise ExceedsReturnableQuantityError(
                self.require_id(), quantity, self.quantity_returnable
            )
        self.quantity_returned += quantity


@dataclass
class PurchaseReceipt(Entity):
    """Una entrega del proveedor, normalmente con su factura (S5.7): lo recibido
    al costo de cada línea de la orden, con su IVA, es lo que se le debe"""

    purchase_order_id: int
    id: int | None = None
    notes: str | None = None
    received_at: datetime | None = None
    supplier_invoice_number: str | None = None
    subtotal: Decimal = ZERO
    tax: Decimal = ZERO
    total: Decimal = ZERO
    created_at: datetime | None = None

    def recalculate_totals(self, lines: Iterable[TaxedLine]) -> None:
        self.subtotal, self.tax, self.total = purchase_totals(lines)


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


class SupplierReturnStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"


@dataclass
class SupplierReturn(Entity):
    """Mercadería recibida de una orden que vuelve al proveedor (S5.7). Al
    confirmarse sale del stock al costo promedio de su ubicación y su total, con
    IVA, baja lo que se le debe al proveedor; lo que no cabe en ese saldo
    (porque ya se le pagó) queda por reembolsar (`refund_due`)"""

    supplier_id: int
    purchase_order_id: int
    number: str | None = None
    id: int | None = None
    status: SupplierReturnStatus = SupplierReturnStatus.DRAFT
    notes: str | None = None
    # The supplier's credit note for it, when there is one
    supplier_credit_note_number: str | None = None
    subtotal: Decimal = ZERO
    tax: Decimal = ZERO
    total: Decimal = ZERO
    # What it took off the supplier's accounts payable when confirmed
    credited_amount: Decimal = ZERO
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def refund_due(self) -> Decimal:
        """Lo que el proveedor debe reembolsar: ya se le había pagado"""
        return self.total - self.credited_amount

    def ensure_draft(self, operation: str) -> None:
        if self.status != SupplierReturnStatus.DRAFT:
            raise InvalidSupplierReturnStatusError(self.status, operation)

    def update_notes(self, notes: str | None) -> None:
        self.ensure_draft("update")
        self.notes = notes

    def recalculate_totals(self, items: Iterable["SupplierReturnItem"]) -> None:
        self.subtotal, self.tax, self.total = purchase_totals(
            item.taxed_line() for item in items
        )

    @staticmethod
    def tax_breakdown(
        items: Iterable["SupplierReturnItem"],
    ) -> dict[TaxCode, tuple[Decimal, Decimal]]:
        """Base imponible e IVA por tarifa, a centavos"""
        return purchase_tax_breakdown(item.taxed_line() for item in items)

    def confirm(
        self,
        item_count: int,
        supplier_credit_note_number: str | None,
        confirmed_by: str | None,
    ) -> None:
        self.ensure_draft("confirm")
        if item_count == 0:
            raise EmptySupplierReturnError(self.number)
        self.status = SupplierReturnStatus.CONFIRMED
        self.supplier_credit_note_number = supplier_credit_note_number
        self.confirmed_by = confirmed_by
        self.confirmed_at = datetime.now()

    def record_credit(self, credited: Decimal) -> None:
        """Lo que la devolución bajó de las cuentas por pagar del proveedor"""
        if credited < 0 or credited > self.total:
            raise SupplierReturnCreditExceedsTotalError(credited, self.total)
        self.credited_amount = credited


@dataclass
class SupplierReturnItem(Entity):
    """Una línea devuelta: una parte de lo recibido de una línea de la orden,
    en su presentación, con el costo y la tarifa que cobró el proveedor"""

    supplier_return_id: int
    purchase_order_item_id: int
    product_id: int
    quantity: Decimal
    unit_cost: Decimal
    id: int | None = None
    tax_code: TaxCode = TaxCode.VAT_15
    tax_amount: Decimal = ZERO
    presentation_id: int | None = None
    unit_factor: Decimal = Decimal(1)
    # Where it leaves from; none: the stock without location, as received
    location_id: int | None = None

    @classmethod
    def of(
        cls,
        supplier_return_id: int,
        order_item: PurchaseOrderItem,
        quantity: Decimal,
        location_id: int | None,
    ) -> "SupplierReturnItem":
        """Una línea de la devolución con los datos de la línea de la orden"""
        item = cls(
            supplier_return_id=supplier_return_id,
            purchase_order_item_id=order_item.require_id(),
            product_id=order_item.product_id,
            quantity=quantity,
            unit_cost=order_item.unit_cost,
            tax_code=order_item.tax_code,
            presentation_id=order_item.presentation_id,
            unit_factor=order_item.unit_factor,
            location_id=location_id,
        )
        item.recalculate_tax()
        return item

    @property
    def subtotal(self) -> Decimal:
        return self.unit_cost * self.quantity

    @property
    def base_quantity(self) -> Decimal:
        """Lo que sale del stock, en unidades base"""
        return self.quantity * self.unit_factor

    def recalculate_tax(self) -> None:
        self.tax_amount = taxed_line(self.tax_code, self.unit_cost, self.quantity)[2]

    def taxed_line(self) -> TaxedLine:
        return self.tax_code, self.subtotal, self.tax_amount

    def update(self, quantity: Decimal, location_id: int | None) -> None:
        self.quantity = quantity
        self.location_id = location_id
        self.recalculate_tax()
