"""The public contracts of the webhooks, version 1 (S6.4, PUBLIC_API.md §7).

Every message is `{id, type, version, occurredAt, tenantId, originClientId,
data}` in camelCase, like the API, with money and quantities as decimal
strings. Each type has its `data`; `sale.confirmed` carries the sale as
`GET /api/v1/sales/{id}` shows it. `docs/public-api/webhooks/v1/` keeps their
JSON Schema (`make public-openapi` writes it, a test fails while it differs).
A field is added without a new version; removing or changing one publishes
`version: 2`. The receivers ignore the fields they don't know.
"""

from typing import Literal
from uuid import UUID

from pydantic import Field

from src.public_api.infra.schemas.base import PublicModel
from src.public_api.infra.schemas.sales import Sale
from src.public_api.infra.types import Quantity, Timestamp
from src.sales.domain.entities import SaleChannel
from src.webhooks.domain.types import TEST_EVENT, WebhookEventType


class SaleCancelledData(PublicModel):
    sale_id: int
    number: str | None = Field(None, description="Of its branch: V-001-000123")
    branch_id: int | None = None
    channel: SaleChannel
    external_reference: str | None = None
    reason: str | None = None


class InvoiceAuthorizedData(PublicModel):
    """Its number, access code and authorization: `GET /api/v1/invoices/{id}`"""

    invoice_id: str = Field(description="Its id in /api/v1/invoices")
    sale_id: int
    sale_number: str | None = None
    branch_id: int | None = None
    external_reference: str | None = None


class InvoiceRejectedData(InvoiceAuthorizedData):
    reason: str | None = Field(
        None, description="The messages of the SRI, joined with ' >> '"
    )


class CreditNoteAuthorizedData(PublicModel):
    credit_note_id: int
    document_id: str = Field(description="Its id in /api/v1/invoices")
    number: str | None = None
    access_code: str | None = None
    authorized_at: Timestamp | None = None
    invoice_id: str = Field(description="The invoice it modifies")
    sale_id: int
    refund_id: int | None = Field(
        None, description="Its refund; null: the whole invoice of a cancelled sale"
    )
    branch_id: int | None = None


class StockChangedData(PublicModel):
    product_id: int
    sku: str
    branch_id: int
    available: Quantity = Field(
        description="In base units, in every location of the branch: what is "
        "there minus what transfers reserved"
    )


class ProductUpdatedData(PublicModel):
    product_id: int
    sku: str
    action: Literal["created", "updated"]
    changed_fields: list[str] = Field(
        description="The fields of the product (GET /api/v1/products/{id}) that "
        "changed; empty when it was created"
    )


class WebhookTestData(PublicModel):
    endpoint_id: int
    message: str


class _Envelope(PublicModel):
    id: str = Field(description="The `webhook-id`: the same in every attempt")
    version: Literal[1]
    occurred_at: Timestamp = Field(description="When it happened")
    tenant_id: UUID = Field(description="The company")
    origin_client_id: str | None = Field(
        None,
        description="The client_id of the integration whose request caused it; "
        "null for a user's or the system's",
    )


class SaleConfirmedEvent(_Envelope):
    type: Literal["sale.confirmed"]
    data: Sale


class SaleCancelledEvent(_Envelope):
    type: Literal["sale.cancelled"]
    data: SaleCancelledData


class InvoiceAuthorizedEvent(_Envelope):
    type: Literal["invoice.authorized"]
    data: InvoiceAuthorizedData


class InvoiceRejectedEvent(_Envelope):
    type: Literal["invoice.rejected"]
    data: InvoiceRejectedData


class CreditNoteAuthorizedEvent(_Envelope):
    type: Literal["credit_note.authorized"]
    data: CreditNoteAuthorizedData


class StockChangedEvent(_Envelope):
    type: Literal["stock.changed"]
    data: StockChangedData


class ProductUpdatedEvent(_Envelope):
    type: Literal["product.updated"]
    data: ProductUpdatedData


class WebhookTestEvent(_Envelope):
    type: Literal["webhook.test"]
    data: WebhookTestData


EVENT_MODELS: dict[str, type[_Envelope]] = {
    WebhookEventType.SALE_CONFIRMED: SaleConfirmedEvent,
    WebhookEventType.SALE_CANCELLED: SaleCancelledEvent,
    WebhookEventType.INVOICE_AUTHORIZED: InvoiceAuthorizedEvent,
    WebhookEventType.INVOICE_REJECTED: InvoiceRejectedEvent,
    WebhookEventType.CREDIT_NOTE_AUTHORIZED: CreditNoteAuthorizedEvent,
    WebhookEventType.STOCK_CHANGED: StockChangedEvent,
    WebhookEventType.PRODUCT_UPDATED: ProductUpdatedEvent,
    TEST_EVENT: WebhookTestEvent,
}


def data_of(model: PublicModel) -> dict:
    """The `data` of a message, as JSON"""
    return model.model_dump(mode="json", by_alias=True)
