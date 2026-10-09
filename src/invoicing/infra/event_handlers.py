"""Integración con faclab-invoicing.

Cada venta confirmada (admin o POS) se publica en el topic `sales.confirmed` con
los datos del cliente y de los productos que necesita la factura. El mensaje se
guarda en el outbox dentro de la transacción de la venta: solo llega a Kafka si
la venta se confirma de verdad.

Cada ítem lleva además `invoice_discount`, `invoice_base` e `invoice_tax`: sus
montos en la factura, redondeados a centavos y con el descuento global ya
prorrateado (ver `invoice_lines`). faclab-invoicing los usa tal cual.

`SaleInvoicingRequested` (reenvío manual) produce el mismo mensaje con un
`event_id` nuevo. faclab-invoicing deduplica por `event_id` y, en un reenvío,
lo ignora si la venta ya tiene una factura que no está rechazada.
"""

from decimal import Decimal
from typing import Any

from src.catalog.product.app.repositories import ProductRepository
from src.customers.app.repositories import CustomerRepository
from src.invoicing.domain.exceptions import InvoicingDisabledError
from src.sales.domain.events import SaleConfirmed, SaleInvoicingRequested
from src.sales.domain.services import SaleLine, invoice_lines
from src.shared.domain.tax import TaxCode
from src.shared.infra.events.decorators import event_handler
from src.shared.infra.events.scope import create_sync_scope
from src.shared.infra.outbox.writer import OutboxWriter

SALES_CONFIRMED_TOPIC = "sales.confirmed"


def build_sale_confirmed_message(
    event: SaleConfirmed | SaleInvoicingRequested,
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
        "aggregate_id": event.aggregate_id,
        "occurred_at": event.occurred_at.isoformat().replace("+00:00", "Z"),
        "payload": {
            "sale_id": event.sale_id,
            "source": event.source,
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
        message = build_sale_confirmed_message(
            event, scope.get(CustomerRepository), scope.get(ProductRepository)
        )
        scope.get(OutboxWriter).add(
            SALES_CONFIRMED_TOPIC,
            message,
            event_type="SaleConfirmed",
            event_id=event.event_id,
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
