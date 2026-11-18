"""The domain events that become webhooks (S6.4, PUBLIC_API.md §7.1).

Each handler runs in the transaction of its event (every publisher passes its
session) and, while some endpoint of the tenant wants the type, enqueues the
message with its public `data`. Nobody subscribed: nothing is built nor
written. The origin of the message is the integration client of the request
that caused it, the context's.
"""

from typing import Any

from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from src.catalog.product.app.repositories import ProductRepository
from src.catalog.product.domain.events import (
    ProductCreated,
    ProductPresentationChanged,
    ProductUpdated,
)
from src.integrations.domain.events import IntegrationClientRevoked
from src.inventory.stock.domain.events import StockCreated, StockUpdated
from src.invoicing.domain.events import CreditNoteAuthorized
from src.public_api.app.queries.sales import GetApiSaleQuery, GetApiSaleQueryHandler
from src.public_api.infra.schemas.products import Product
from src.public_api.infra.schemas.sales import Sale as PublicSale
from src.sales.app.repositories import SaleRepository
from src.sales.domain.entities import Sale
from src.sales.domain.events import (
    SaleCancelled,
    SaleConfirmed,
    SaleInvoiced,
    SaleInvoiceRejected,
)
from src.shared.domain.exceptions import NotFoundError
from src.shared.infra.events.decorators import event_handler
from src.shared.infra.events.scope import create_sync_scope
from src.webhooks.app.commands.endpoints import (
    DisableClientWebhookEndpointsCommand,
    DisableClientWebhookEndpointsCommandHandler,
)
from src.webhooks.app.outbox import WebhookOutbox
from src.webhooks.domain.types import WebhookEventType
from src.webhooks.infra.schemas import (
    CreditNoteAuthorizedData,
    InvoiceAuthorizedData,
    InvoiceRejectedData,
    ProductUpdatedData,
    SaleCancelledData,
    data_of,
)
from src.webhooks.infra.stock_changes import record_stock_change

# The fields of a product an integration reads (GET /api/v1/products/{id}):
# only their changes are told
PUBLIC_PRODUCT_FIELDS = frozenset(Product.model_fields) - {
    "id",
    "created_at",
    "updated_at",
    "unit_symbol",
    "quantity_decimals",
    "presentations",
}


def _sale(scope: Any, sale_id: int) -> Sale:
    sale = scope.get(SaleRepository).get_by_id(sale_id)
    if sale is None:
        raise NotFoundError(f"Sale with id {sale_id} not found")
    return sale


@event_handler(SaleConfirmed)
def sale_confirmed(event: SaleConfirmed, session: Any = None) -> None:
    with create_sync_scope(session) as scope:
        outbox = scope.get(WebhookOutbox)
        if not outbox.subscribed(WebhookEventType.SALE_CONFIRMED):
            return
        sale = scope.get(GetApiSaleQueryHandler).handle(
            GetApiSaleQuery(sale_id=event.sale_id)
        )
        outbox.enqueue(
            WebhookEventType.SALE_CONFIRMED,
            data_of(PublicSale.model_validate(sale)),
            branch_id=sale["branch_id"],
            occurred_at=event.occurred_at,
        )


@event_handler(SaleCancelled)
def sale_cancelled(event: SaleCancelled, session: Any = None) -> None:
    with create_sync_scope(session) as scope:
        outbox = scope.get(WebhookOutbox)
        if not outbox.subscribed(WebhookEventType.SALE_CANCELLED):
            return
        sale = _sale(scope, event.sale_id)
        outbox.enqueue(
            WebhookEventType.SALE_CANCELLED,
            data_of(
                SaleCancelledData(
                    sale_id=sale.require_id(),
                    number=sale.number,
                    branch_id=sale.branch_id,
                    channel=sale.channel,
                    external_reference=sale.external_reference,
                    reason=event.reason or None,
                )
            ),
            branch_id=sale.branch_id,
            occurred_at=event.occurred_at,
        )


@event_handler(SaleInvoiced)
def invoice_authorized(event: SaleInvoiced, session: Any = None) -> None:
    with create_sync_scope(session) as scope:
        outbox = scope.get(WebhookOutbox)
        if not outbox.subscribed(WebhookEventType.INVOICE_AUTHORIZED):
            return
        sale = _sale(scope, event.sale_id)
        outbox.enqueue(
            WebhookEventType.INVOICE_AUTHORIZED,
            data_of(
                InvoiceAuthorizedData(
                    invoice_id=event.invoice_id,
                    sale_id=sale.require_id(),
                    sale_number=sale.number,
                    branch_id=sale.branch_id,
                    external_reference=sale.external_reference,
                )
            ),
            branch_id=sale.branch_id,
            occurred_at=event.occurred_at,
        )


@event_handler(SaleInvoiceRejected)
def invoice_rejected(event: SaleInvoiceRejected, session: Any = None) -> None:
    with create_sync_scope(session) as scope:
        outbox = scope.get(WebhookOutbox)
        if not outbox.subscribed(WebhookEventType.INVOICE_REJECTED):
            return
        sale = _sale(scope, event.sale_id)
        outbox.enqueue(
            WebhookEventType.INVOICE_REJECTED,
            data_of(
                InvoiceRejectedData(
                    invoice_id=event.invoice_id,
                    sale_id=sale.require_id(),
                    sale_number=sale.number,
                    branch_id=sale.branch_id,
                    external_reference=sale.external_reference,
                    reason=event.reason,
                )
            ),
            branch_id=sale.branch_id,
            occurred_at=event.occurred_at,
        )


@event_handler(CreditNoteAuthorized)
def credit_note_authorized(event: CreditNoteAuthorized, session: Any = None) -> None:
    with create_sync_scope(session) as scope:
        outbox = scope.get(WebhookOutbox)
        if not outbox.subscribed(WebhookEventType.CREDIT_NOTE_AUTHORIZED):
            return
        sale = _sale(scope, event.sale_id)
        outbox.enqueue(
            WebhookEventType.CREDIT_NOTE_AUTHORIZED,
            data_of(
                CreditNoteAuthorizedData(
                    credit_note_id=event.credit_note_id,
                    document_id=event.document_id,
                    number=event.number,
                    access_code=event.access_code,
                    authorized_at=event.authorized_at,
                    invoice_id=event.invoice_id,
                    sale_id=event.sale_id,
                    refund_id=event.refund_id,
                    branch_id=sale.branch_id,
                )
            ),
            branch_id=sale.branch_id,
            occurred_at=event.occurred_at,
        )


def _product_updated(
    session: Any, product_id: int, created: bool, fields: list[str], event: Any
) -> None:
    with create_sync_scope(session) as scope:
        outbox = scope.get(WebhookOutbox)
        if not outbox.subscribed(WebhookEventType.PRODUCT_UPDATED):
            return
        product = scope.get(ProductRepository).get_by_id(product_id)
        if product is None:
            return
        outbox.enqueue(
            WebhookEventType.PRODUCT_UPDATED,
            data_of(
                ProductUpdatedData(
                    product_id=product_id,
                    sku=product.sku,
                    action="created" if created else "updated",
                    changed_fields=fields,
                )
            ),
            branch_id=None,
            occurred_at=event.occurred_at,
        )


@event_handler(ProductCreated)
def product_created(event: ProductCreated, session: Any = None) -> None:
    _product_updated(session, event.product_id, True, [], event)


@event_handler(ProductUpdated)
def product_updated(event: ProductUpdated, session: Any = None) -> None:
    fields = sorted(
        to_camel(name)
        for name in (event.changes or {})
        if name in PUBLIC_PRODUCT_FIELDS
    )
    # Its cost or stock thresholds aren't public: nothing an integration sees
    if fields:
        _product_updated(session, event.product_id, False, fields, event)


@event_handler(ProductPresentationChanged)
def presentation_changed(
    event: ProductPresentationChanged, session: Any = None
) -> None:
    _product_updated(session, event.product_id, False, ["presentations"], event)


@event_handler(StockCreated)
def stock_created(event: StockCreated, session: Any = None) -> None:
    with create_sync_scope(session) as scope:
        record_stock_change(
            scope.get(Session),
            scope.get(WebhookOutbox),
            event.product_id,
            event.location_id,
        )


@event_handler(StockUpdated)
def stock_updated(event: StockUpdated, session: Any = None) -> None:
    with create_sync_scope(session) as scope:
        record_stock_change(
            scope.get(Session),
            scope.get(WebhookOutbox),
            event.product_id,
            event.location_id,
        )


@event_handler(IntegrationClientRevoked)
def client_revoked(event: IntegrationClientRevoked, session: Any = None) -> None:
    with create_sync_scope(session) as scope:
        scope.get(DisableClientWebhookEndpointsCommandHandler).handle(
            DisableClientWebhookEndpointsCommand(integration_client_id=event.client_id)
        )
