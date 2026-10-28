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
lo ignora si la venta ya tiene una factura que no está rechazada.

Con el mensaje en el outbox la factura de la venta queda pendiente
(`invoice_status = PENDING`): la venta no se cancela hasta que el SRI responda
(`INVOICE_IN_PROGRESS`, ver `invoice_messages.py`).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.catalog.product.app.repositories import ProductRepository
from src.customers.app.repositories import CustomerRepository
from src.invoicing.domain.exceptions import InvoicingDisabledError
from src.organization.app.repositories import BranchRepository, EmissionPointRepository
from src.sales.app.repositories import SaleRepository
from src.sales.domain.events import SaleConfirmed, SaleInvoicingRequested
from src.sales.domain.exceptions import SaleWithoutEmissionPointError
from src.sales.domain.services import SaleLine, invoice_lines
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
    tenant_id = require_tenant("invoicing a sale").tenant_id
    point = (
        emission_point_repo.get_by_id(event.emission_point_id)
        if event.emission_point_id is not None
        else None
    )
    branch = branch_repo.get_by_id(point.branch_id) if point else None
    tenant = tenant_repo.get(tenant_id)
    if point is None or branch is None or tenant is None:
        raise SaleWithoutEmissionPointError(event.sale_id)
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
