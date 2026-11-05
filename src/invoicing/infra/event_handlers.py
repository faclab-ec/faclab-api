"""Integración con faclab-invoicing.

Cada venta confirmada (admin o POS) se publica en el topic `sales.confirmed` con
los datos del cliente y de los productos que necesita la factura. El mensaje se
guarda en el outbox dentro de la transacción de la venta: solo llega a Kafka si
la venta se confirma de verdad. Su forma es el contrato
`contracts/events/sales.confirmed/v2.schema.json`, que `tests/contract` verifica.

El mensaje dice quién emite y desde dónde: la empresa (`tenant_id`, que también
es la clave del mensaje en Kafka), su RUC, el establecimiento y la dirección de
la sucursal y el punto de emisión de la venta. faclab-invoicing usa el perfil
fiscal, el certificado y el secuencial de esa empresa, establecimiento y punto
de emisión. Una venta sin punto de emisión (anterior a S2.6) no se puede
facturar: `SALE_WITHOUT_EMISSION_POINT`.

Cada ítem lleva además `invoice_discount`, `invoice_base` e `invoice_tax`: sus
montos en la factura, redondeados a centavos y con el descuento global ya
prorrateado (ver `invoice_lines`). faclab-invoicing los usa tal cual.

`SaleInvoicingRequested` (reenvío manual) produce el mismo mensaje con un
`event_id` nuevo. faclab-invoicing deduplica por `event_id` y, en un reenvío,
lo ignora si la venta ya tiene una factura en curso; si ya la autorizó, vuelve a
publicar el resultado.

Con el mensaje en el outbox la factura de la venta queda pendiente
(`invoice_status = PENDING`, desde `invoice_requested_at`): la venta no se
cancela hasta que el SRI responda (`INVOICE_IN_PROGRESS`, ver
`invoice_messages.py`). Su discrepancia `confirmed_without_result`, si la tenía,
se resuelve en la misma transacción (ver `reconciliation.py`).

Nota de crédito (S4.5): una devolución completada de una venta facturada la pide
en su transacción; la de una venta aún sin autorizar, cuando se autoriza
(`SaleInvoiced`). El mensaje de `credit_notes.requested` dice qué se acredita y
desde dónde; el comprador, el número y la fecha de la factura los pone
faclab-invoicing (contrato `contracts/events/credit_notes.requested/v1`).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.catalog.product.app.repositories import ProductRepository
from src.customers.app.repositories import CustomerRepository
from src.invoicing.app.commands.credit_notes import (
    RequestRefundCreditNotesCommand,
    RequestRefundCreditNotesCommandHandler,
)
from src.invoicing.app.commands.discrepancies import (
    ResolveInvoiceDiscrepancyCommand,
    ResolveInvoiceDiscrepancyCommandHandler,
)
from src.invoicing.app.repositories import CreditNoteRepository
from src.invoicing.domain.entities import CreditNote
from src.invoicing.domain.events import CreditNoteRequested
from src.invoicing.domain.exceptions import (
    CreditNotesDisabledError,
    InvoicingDisabledError,
)
from src.organization.app.repositories import (
    BranchRepository,
    EmissionPointRepository,
    PosTerminalRepository,
)
from src.pos.refund.app.repositories import RefundItemRepository, RefundRepository
from src.pos.refund.domain.entities import Refund, RefundItem
from src.pos.refund.domain.events import RefundCompleted
from src.sales.app.repositories import SaleItemRepository, SaleRepository
from src.sales.domain.entities import Sale, SaleItem
from src.sales.domain.events import SaleConfirmed, SaleInvoiced, SaleInvoicingRequested
from src.sales.domain.exceptions import SaleWithoutEmissionPointError
from src.sales.domain.services import InvoiceLine, SaleLine, invoice_lines
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tax import TaxCode
from src.shared.domain.tenant import require_tenant
from src.shared.infra.events.decorators import event_handler
from src.shared.infra.events.scope import create_sync_scope
from src.shared.infra.outbox.writer import OutboxWriter
from src.tenancy.app.repositories import TenantRepository

SALES_CONFIRMED_TOPIC = "sales.confirmed"
# Versión del esquema en contracts/events/sales.confirmed/ (ver contracts/README.md)
SALES_CONFIRMED_SCHEMA_VERSION = 2

CREDIT_NOTES_REQUESTED_TOPIC = "credit_notes.requested"
# Versión del esquema en contracts/events/credit_notes.requested/
CREDIT_NOTES_REQUESTED_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class IssuingPoint:
    """Quién emite la factura de una venta y desde dónde"""

    tenant_id: UUID
    issuer_ruc: str
    establishment_code: str
    establishment_address: str | None
    emission_point_code: str


def issuing_point(
    event: SaleConfirmed | SaleInvoicingRequested,
    tenant_repo: TenantRepository,
    branch_repo: BranchRepository,
    emission_point_repo: EmissionPointRepository,
) -> IssuingPoint:
    """La empresa del contexto y el establecimiento y punto de emisión de la
    venta (el de su terminal, copiado al crearla)"""
    return _issuing_point(
        event.sale_id,
        event.emission_point_id,
        tenant_repo,
        branch_repo,
        emission_point_repo,
    )


def _issuing_point(
    sale_id: int,
    emission_point_id: int | None,
    tenant_repo: TenantRepository,
    branch_repo: BranchRepository,
    emission_point_repo: EmissionPointRepository,
) -> IssuingPoint:
    tenant_id = require_tenant("invoicing a sale").tenant_id
    point = (
        emission_point_repo.get_by_id(emission_point_id)
        if emission_point_id is not None
        else None
    )
    branch = branch_repo.get_by_id(point.branch_id) if point else None
    tenant = tenant_repo.get(tenant_id)
    if point is None or branch is None or tenant is None:
        raise SaleWithoutEmissionPointError(sale_id)
    return IssuingPoint(
        tenant_id=tenant_id,
        issuer_ruc=tenant.ruc,
        establishment_code=branch.establishment_code,
        establishment_address=branch.address,
        emission_point_code=point.code,
    )


def build_sale_confirmed_message(
    event: SaleConfirmed | SaleInvoicingRequested,
    point: IssuingPoint,
    customer_repo: CustomerRepository,
    product_repo: ProductRepository,
) -> dict[str, Any]:
    customer_data = None
    if event.customer_id:
        customer = customer_repo.get_by_id(event.customer_id)
        if customer:
            customer_data = {
                "id": customer.id,
                "name": customer.name,
                "tax_id": customer.tax_id,
                "tax_type": customer.tax_type.name,
                "email": customer.email,
                "phone": customer.phone,
                "address": customer.address,
            }

    products = {
        p.id: p
        for p in product_repo.get_by_ids(item["product_id"] for item in event.items)
    }
    lines = invoice_lines(
        [
            SaleLine(
                gross=Decimal(item["quantity"]) * Decimal(item["unit_price"]),
                tax_code=TaxCode(item["tax_code"]),
                subtotal=Decimal(item.get("subtotal", 0)),
                tax_amount=Decimal(item.get("tax_amount", 0)),
            )
            for item in event.items
        ],
        subtotal=event.subtotal,
        discount=event.total_discount,
        tax=event.total - event.subtotal + event.total_discount,
    )
    items = []
    for item, line in zip(event.items, lines, strict=True):
        product = products.get(item["product_id"])
        items.append(
            {
                "product_id": item["product_id"],
                "sku": product.sku if product else None,
                "product_name": product.name if product else None,
                "quantity": item["quantity"],
                "unit_price": item["unit_price"],
                "discount": item.get("discount", 0),
                "tax_code": item.get("tax_code"),
                "tax_amount": item.get("tax_amount", 0),
                "subtotal": item.get("subtotal", 0),
                "invoice_discount": line.discount,
                "invoice_base": line.taxable_base,
                "invoice_tax": line.tax,
            }
        )

    return {
        "event_id": event.event_id,
        "event_type": "SaleConfirmed",
        "schema_version": SALES_CONFIRMED_SCHEMA_VERSION,
        "tenant_id": str(point.tenant_id),
        "aggregate_id": event.aggregate_id,
        "occurred_at": event.occurred_at.isoformat().replace("+00:00", "Z"),
        "payload": {
            "sale_id": event.sale_id,
            "sale_number": event.number,
            "source": event.source,
            "issuer_ruc": point.issuer_ruc,
            "establishment_code": point.establishment_code,
            "establishment_address": point.establishment_address,
            "emission_point_code": point.emission_point_code,
            "subtotal": event.subtotal,
            "total_discount": event.total_discount,
            "total": event.total,
            "customer": customer_data,
            "items": items,
            "payments": event.payments,
        },
    }


def _enqueue(event: SaleConfirmed | SaleInvoicingRequested, session: Any) -> None:
    with create_sync_scope(session) as scope:
        point = issuing_point(
            event,
            scope.get(TenantRepository),
            scope.get(BranchRepository),
            scope.get(EmissionPointRepository),
        )
        message = build_sale_confirmed_message(
            event, point, scope.get(CustomerRepository), scope.get(ProductRepository)
        )
        scope.get(OutboxWriter).add(
            SALES_CONFIRMED_TOPIC,
            message,
            event_type="SaleConfirmed",
            event_id=event.event_id,
        )
        # The sale's own handler publishes last and writes the sale no more
        # after it, so this change is not overwritten
        sales = scope.get(SaleRepository)
        sale = sales.get_by_id(event.sale_id)
        if sale is None:
            raise NotFoundError(f"Sale with id {event.sale_id} not found")
        sale.await_invoice()
        sales.update(sale)
        # Sent again: it no longer waits since before the threshold
        scope.get(ResolveInvoiceDiscrepancyCommandHandler).handle(
            ResolveInvoiceDiscrepancyCommand(sale_id=event.sale_id)
        )


@event_handler(SaleConfirmed)
def enqueue_sale_confirmed(event: SaleConfirmed, session: Any = None) -> None:
    from config import config

    if not config.KAFKA_ENABLED:
        return
    _enqueue(event, session)


@event_handler(SaleInvoicingRequested)
def enqueue_invoicing_request(
    event: SaleInvoicingRequested, session: Any = None
) -> None:
    from config import config

    # Pedido a mano: callar aquí escondería que no se envía nada
    if not config.KAFKA_ENABLED:
        raise InvoicingDisabledError()
    _enqueue(event, session)


def credit_note_lines(
    note: CreditNote, items: Sequence[RefundItem] | Sequence[SaleItem]
) -> list[InvoiceLine]:
    """Sus montos por línea, como en la factura: redondeados a centavos y con el
    descuento global ya prorrateado. Las bases suman `note.subtotal` y el IVA
    `note.tax`, así que `valorModificacion` es lo que se acredita."""
    gross = sum((item.subtotal for item in items), Decimal("0"))
    return invoice_lines(
        [
            SaleLine(
                gross=item.unit_price * item.quantity,
                tax_code=item.tax_code,
                subtotal=item.subtotal,
                tax_amount=item.tax_amount,
            )
            for item in items
        ],
        subtotal=gross,
        discount=gross - note.subtotal,
        tax=note.tax,
    )


def build_credit_note_message(
    event: CreditNoteRequested,
    note: CreditNote,
    refund: Refund | None,
    items: Sequence[RefundItem] | Sequence[SaleItem],
    point: IssuingPoint,
    product_repo: ProductRepository,
) -> dict[str, Any]:
    products = {
        p.id: p for p in product_repo.get_by_ids(item.product_id for item in items)
    }
    lines = credit_note_lines(note, items)
    message_items = []
    for item, line in zip(items, lines, strict=True):
        product = products.get(item.product_id)
        message_items.append(
            {
                "product_id": item.product_id,
                "sku": product.sku if product else None,
                "product_name": product.name if product else None,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "tax_code": item.tax_code,
                "invoice_discount": line.discount,
                "invoice_base": line.taxable_base,
                "invoice_tax": line.tax,
            }
        )
    return {
        "event_id": event.event_id,
        "event_type": "CreditNoteRequested",
        "schema_version": CREDIT_NOTES_REQUESTED_SCHEMA_VERSION,
        "tenant_id": str(point.tenant_id),
        "aggregate_id": note.require_id(),
        "occurred_at": event.occurred_at.isoformat().replace("+00:00", "Z"),
        "payload": {
            "credit_note_id": note.require_id(),
            "sale_id": note.sale_id,
            "invoice_id": note.invoice_id,
            "refund_id": note.refund_id,
            "refund_number": refund.number if refund else None,
            "issuer_ruc": point.issuer_ruc,
            "establishment_code": point.establishment_code,
            "establishment_address": point.establishment_address,
            "emission_point_code": point.emission_point_code,
            "reason": note.reason,
            "subtotal": sum((line.taxable_base for line in lines), Decimal("0")),
            "tax": sum((line.tax for line in lines), Decimal("0")),
            "total": note.total,
            "items": message_items,
        },
    }


def _emission_point_of(
    refund: Refund | None, sale: Sale, terminals: PosTerminalRepository
) -> int | None:
    """El de la terminal donde se hizo la devolución o, si no hay, el de la venta"""
    if refund is not None and refund.terminal_id is not None:
        terminal = terminals.get_by_id(refund.terminal_id)
        if terminal is not None:
            return terminal.emission_point_id
    return sale.emission_point_id


@event_handler(CreditNoteRequested)
def enqueue_credit_note(event: CreditNoteRequested, session: Any = None) -> None:
    from config import config

    # Pedida a mano: callar aquí escondería que no se envía nada
    if not config.KAFKA_ENABLED:
        raise InvoicingDisabledError()
    if not config.CREDIT_NOTES_ENABLED:
        raise CreditNotesDisabledError()

    with create_sync_scope(session) as scope:
        note = scope.get(CreditNoteRepository).get_by_id(event.credit_note_id)
        if note is None:
            raise NotFoundError(f"Credit note {event.credit_note_id} not found")
        sale = scope.get(SaleRepository).get_by_id(note.sale_id)
        if sale is None:
            raise NotFoundError(f"Sale with id {note.sale_id} not found")
        refund = (
            scope.get(RefundRepository).get_by_id(note.refund_id)
            if note.refund_id is not None
            else None
        )
        items: Sequence[RefundItem] | Sequence[SaleItem] = (
            scope.get(RefundItemRepository).filter_by(refund_id=note.refund_id)
            if note.refund_id is not None
            else scope.get(SaleItemRepository).filter_by(sale_id=note.sale_id)
        )
        point = _issuing_point(
            note.sale_id,
            _emission_point_of(refund, sale, scope.get(PosTerminalRepository)),
            scope.get(TenantRepository),
            scope.get(BranchRepository),
            scope.get(EmissionPointRepository),
        )
        message = build_credit_note_message(
            event, note, refund, items, point, scope.get(ProductRepository)
        )
        scope.get(OutboxWriter).add(
            CREDIT_NOTES_REQUESTED_TOPIC,
            message,
            event_type="CreditNoteRequested",
            event_id=event.event_id,
        )


def _request_refund_credit_notes(sale_id: int, session: Any) -> None:
    from config import config

    if not (config.KAFKA_ENABLED and config.CREDIT_NOTES_ENABLED):
        return
    with create_sync_scope(session) as scope:
        scope.get(RequestRefundCreditNotesCommandHandler).handle(
            RequestRefundCreditNotesCommand(sale_id=sale_id)
        )


@event_handler(RefundCompleted)
def request_credit_note_of_refund(event: RefundCompleted, session: Any = None) -> None:
    _request_refund_credit_notes(event.original_sale_id, session)


@event_handler(SaleInvoiced)
def request_credit_notes_of_invoiced_sale(
    event: SaleInvoiced, session: Any = None
) -> None:
    """Las devoluciones que se hicieron con la factura aún sin autorizar"""
    _request_refund_credit_notes(event.sale_id, session)
