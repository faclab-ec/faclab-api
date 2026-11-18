from dataclasses import dataclass
from datetime import datetime, timedelta

from wireup import injectable

from src.shared.app.queries import Query, QueryHandler
from src.webhooks.app.commands.endpoints import get_endpoint
from src.webhooks.app.ports import SecretBox, WebhookSettings
from src.webhooks.app.repositories import (
    WebhookDeliveryRepository,
    WebhookEndpointRepository,
)
from src.webhooks.app.views import describe_endpoint
from src.webhooks.domain.entities import WebhookDeliveryStatus, WebhookEndpointStatus


@dataclass
class ListWebhookEndpointsQuery(Query):
    as_client_id: int | None = None
    status: WebhookEndpointStatus | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class ListWebhookEndpointsQueryHandler(QueryHandler[ListWebhookEndpointsQuery, dict]):
    def __init__(self, endpoints: WebhookEndpointRepository):
        self.endpoints = endpoints

    def _handle(self, query: ListWebhookEndpointsQuery) -> dict:
        endpoints, total = self.endpoints.page(
            query.as_client_id, query.status, query.limit, query.offset
        )
        return {
            "total": total,
            "limit": query.limit,
            "offset": query.offset,
            "items": [describe_endpoint(endpoint) for endpoint in endpoints],
        }


@dataclass
class GetWebhookEndpointQuery(Query):
    endpoint_id: int
    as_client_id: int | None = None


@injectable(lifetime="scoped")
class GetWebhookEndpointQueryHandler(QueryHandler[GetWebhookEndpointQuery, dict]):
    def __init__(self, endpoints: WebhookEndpointRepository):
        self.endpoints = endpoints

    def _handle(self, query: GetWebhookEndpointQuery) -> dict:
        return describe_endpoint(
            get_endpoint(self.endpoints, query.endpoint_id, query.as_client_id)
        )


@dataclass
class GetWebhookSecretQuery(Query):
    endpoint_id: int
    as_client_id: int | None = None


@injectable(lifetime="scoped")
class GetWebhookSecretQueryHandler(QueryHandler[GetWebhookSecretQuery, dict]):
    """The secret that signs the endpoint's messages, and the previous one while
    a rotation lets it sign too"""

    def __init__(self, endpoints: WebhookEndpointRepository, box: SecretBox):
        self.endpoints = endpoints
        self.box = box

    def _handle(self, query: GetWebhookSecretQuery) -> dict:
        endpoint = get_endpoint(self.endpoints, query.endpoint_id, query.as_client_id)
        sealed = endpoint.signing_secrets(datetime.now())
        return {
            "secret": self.box.open(sealed[0]),
            "previous_secret": self.box.open(sealed[1]) if len(sealed) > 1 else None,
            "previous_expires_at": (
                endpoint.previous_secret_expires_at if len(sealed) > 1 else None
            ),
        }


@dataclass
class ListWebhookDeliveriesQuery(Query):
    endpoint_id: int
    as_client_id: int | None = None
    status: WebhookDeliveryStatus | None = None
    event_type: str | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class ListWebhookDeliveriesQueryHandler(QueryHandler[ListWebhookDeliveriesQuery, dict]):
    """The endpoint's deliveries of the retention (30 days), newest first"""

    def __init__(
        self,
        endpoints: WebhookEndpointRepository,
        deliveries: WebhookDeliveryRepository,
        settings: WebhookSettings,
    ):
        self.endpoints = endpoints
        self.deliveries = deliveries
        self.settings = settings

    def _handle(self, query: ListWebhookDeliveriesQuery) -> dict:
        endpoint = get_endpoint(self.endpoints, query.endpoint_id, query.as_client_id)
        since = datetime.now() - timedelta(days=self.settings.retention_days)
        items, total = self.deliveries.history(
            endpoint.require_id(),
            since,
            query.status,
            query.event_type,
            query.limit,
            query.offset,
        )
        return {
            "total": total,
            "limit": query.limit,
            "offset": query.offset,
            "items": items,
        }
