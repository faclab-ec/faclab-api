"""The public webhook events (S6.4, PUBLIC_API.md §7.1) and what an endpoint
needs to receive each one."""

from enum import StrEnum

from src.auth.domain.scopes import Scope

# The version of the envelope and of every `data` (PUBLIC_API.md §8): an
# incompatible change publishes `version: 2` next to it
CONTRACT_VERSION = 1


class WebhookEventType(StrEnum):
    """What an endpoint subscribes to. A new type is a compatible change"""

    SALE_CONFIRMED = "sale.confirmed"
    SALE_CANCELLED = "sale.cancelled"
    INVOICE_AUTHORIZED = "invoice.authorized"
    INVOICE_REJECTED = "invoice.rejected"
    CREDIT_NOTE_AUTHORIZED = "credit_note.authorized"
    STOCK_CHANGED = "stock.changed"
    PRODUCT_UPDATED = "product.updated"


# Sent to one endpoint on request (`POST …/test`), never subscribed to
TEST_EVENT = "webhook.test"

# An endpoint of an integration client only gets the events its client may
# read through the API: the scope of each type
REQUIRED_SCOPE = {
    WebhookEventType.SALE_CONFIRMED: Scope.SALES_READ,
    WebhookEventType.SALE_CANCELLED: Scope.SALES_READ,
    WebhookEventType.INVOICE_AUTHORIZED: Scope.INVOICES_READ,
    WebhookEventType.INVOICE_REJECTED: Scope.INVOICES_READ,
    WebhookEventType.CREDIT_NOTE_AUTHORIZED: Scope.INVOICES_READ,
    WebhookEventType.STOCK_CHANGED: Scope.STOCK_READ,
    WebhookEventType.PRODUCT_UPDATED: Scope.PRODUCTS_READ,
}

# The events of a branch: a client limited to some branches only gets the ones
# of its branches (and none of a sale without branch, older than S2.6)
BRANCH_SCOPED = frozenset(WebhookEventType) - {WebhookEventType.PRODUCT_UPDATED}


def missing_scopes(
    event_types: frozenset[WebhookEventType], scopes: frozenset[Scope]
) -> list[str]:
    """The scopes a client lacks to receive these events"""
    return sorted({REQUIRED_SCOPE[t].value for t in event_types} - scopes)
