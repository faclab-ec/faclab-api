from typing import Any

import structlog

from src.sales.domain.events import SaleConfirmed
from src.shared.infra.events.decorators import event_handler
from src.shared.infra.events.scope import create_sync_scope
from src.shared.infra.kafka.producer import KafkaEventProducer

logger = structlog.get_logger(__name__)

_producer: KafkaEventProducer | None = None


def _get_producer() -> KafkaEventProducer | None:
    global _producer
    if _producer is None:
        from config import config

        if not config.KAFKA_ENABLED:
            return None

        _producer = KafkaEventProducer(config.KAFKA_BOOTSTRAP_SERVERS)
        _producer.start()

    return _producer


def _build_enriched_payload(event: SaleConfirmed, session: Any = None) -> dict:
    from src.catalog.product.app.repositories import ProductRepository
    from src.customers.app.repositories import CustomerRepository

    customer_data = None
    enriched_items = []

    with create_sync_scope(session) as scope:
        if event.customer_id:
            customer_repo = scope.get(CustomerRepository)
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

        product_repo = scope.get(ProductRepository)
        product_ids = {item["product_id"] for item in event.items}
        products = {
            p.id: p for p in (product_repo.get_by_id(pid) for pid in product_ids) if p
        }

    for item in event.items:
        product = products.get(item["product_id"])
        enriched_items.append(
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
            "items": enriched_items,
            "payments": event.payments,
        },
    }


@event_handler(SaleConfirmed)
def publish_sale_confirmed_to_kafka(event: SaleConfirmed, session: Any = None) -> None:
    producer = _get_producer()
    if producer is None:
        return

    try:
        enriched = _build_enriched_payload(event, session=session)
        producer.send_raw("sales.confirmed", enriched, event_type="SaleConfirmed")
    except Exception:
        logger.error(
            "kafka_enrichment_error",
            sale_id=event.sale_id,
            exc_info=True,
        )
        producer.send("sales.confirmed", event)
