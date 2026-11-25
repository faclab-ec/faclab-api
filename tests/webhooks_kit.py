"""Runs the webhook commands (S6.4) over a SQLite session with the real
repositories, a fake audit trail, a test master key and a resolver that
answers from a table instead of the DNS."""

from collections.abc import Callable
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from src.auth.domain.scopes import Scope
from src.integrations.domain.credentials import IntegrationEnvironment
from src.integrations.domain.entities import IntegrationClient
from src.integrations.infra.mappers import IntegrationClientMapper
from src.integrations.infra.models import IntegrationClientModel
from src.integrations.infra.repositories import SqlAlchemyIntegrationClientRepository
from src.webhooks.app.commands.endpoints import (
    CreateWebhookEndpointCommand,
    CreateWebhookEndpointCommandHandler,
    DeleteWebhookEndpointCommand,
    DeleteWebhookEndpointCommandHandler,
    DisableClientWebhookEndpointsCommand,
    DisableClientWebhookEndpointsCommandHandler,
    DisableFailingWebhookEndpointCommand,
    DisableFailingWebhookEndpointCommandHandler,
    DisableWebhookEndpointCommand,
    DisableWebhookEndpointCommandHandler,
    EnableWebhookEndpointCommand,
    EnableWebhookEndpointCommandHandler,
    RetryWebhookDeliveryCommand,
    RetryWebhookDeliveryCommandHandler,
    RotateWebhookSecretCommand,
    RotateWebhookSecretCommandHandler,
    SendTestWebhookCommand,
    SendTestWebhookCommandHandler,
    UpdateWebhookEndpointCommand,
    UpdateWebhookEndpointCommandHandler,
)
from src.webhooks.app.outbox import WebhookOutbox
from src.webhooks.app.ports import WebhookSettings
from src.webhooks.app.queries.endpoints import (
    GetWebhookEndpointQuery,
    GetWebhookEndpointQueryHandler,
    GetWebhookSecretQuery,
    GetWebhookSecretQueryHandler,
    ListWebhookDeliveriesQuery,
    ListWebhookDeliveriesQueryHandler,
    ListWebhookEndpointsQuery,
    ListWebhookEndpointsQueryHandler,
)
from src.webhooks.domain.types import WebhookEventType
from src.webhooks.infra.mappers import WebhookDeliveryMapper, WebhookEndpointMapper
from src.webhooks.infra.models import (
    WebhookDeliveryModel,
    WebhookEndpointModel,
    WebhookMessageModel,
    WebhookStockChangeModel,
)
from src.webhooks.infra.repositories import (
    SqlAlchemyWebhookDeliveryRepository,
    SqlAlchemyWebhookEndpointRepository,
    SqlAlchemyWebhookQueue,
)
from src.webhooks.infra.secrets import FernetSecretBox
from src.webhooks.infra.urls import DnsUrlGuard
from tests.audit import FakeAuditTrail
from tests.plans import FakePlanLimits

WEBHOOK_MODELS = [
    IntegrationClientModel,
    WebhookEndpointModel,
    WebhookMessageModel,
    WebhookDeliveryModel,
    WebhookStockChangeModel,
]
URL = "https://hooks.tienda.example/faclab"
# The names the fake resolver knows: one public, one private
PUBLIC_ADDRESS = "93.184.215.14"
ADDRESSES = {
    "hooks.tienda.example": [PUBLIC_ADDRESS],
    "otro.tienda.example": [PUBLIC_ADDRESS],
    "interno.tienda.example": ["10.0.0.5"],
}


def table_resolver(
    table: dict[str, list[str]] | None = None,
) -> Callable[[str, int], list[str]]:
    names = ADDRESSES if table is None else table

    def resolve(host: str, _port: int) -> list[str]:
        if host not in names:
            raise OSError("unknown host")
        return names[host]

    return resolve


def fernet_box() -> FernetSecretBox:
    return FernetSecretBox([Fernet.generate_key().decode()])


class Kit:
    def __init__(
        self,
        session: Session,
        box: FernetSecretBox | None = None,
        guard: DnsUrlGuard | None = None,
        settings: WebhookSettings | None = None,
    ):
        self.session = session
        self.audit = FakeAuditTrail()
        self.limits = FakePlanLimits()
        self.box = box or fernet_box()
        self.guard = guard or DnsUrlGuard(resolver=table_resolver())
        self.settings = settings or WebhookSettings()
        self.clients = SqlAlchemyIntegrationClientRepository(
            session, IntegrationClientMapper()
        )
        self.endpoints = SqlAlchemyWebhookEndpointRepository(
            session, WebhookEndpointMapper()
        )
        self.deliveries = SqlAlchemyWebhookDeliveryRepository(
            session, WebhookDeliveryMapper()
        )
        self.queue = SqlAlchemyWebhookQueue(session)

    @property
    def outbox(self) -> WebhookOutbox:
        return WebhookOutbox(SqlAlchemyWebhookQueue(self.session), self.settings)

    def client(
        self,
        scopes: list[Scope] | None = None,
        branch_ids: list[int] | None = None,
        name: str = "Tienda web",
    ) -> IntegrationClient:
        client = IntegrationClient.new(
            IntegrationEnvironment.SANDBOX,
            name,
            scopes
            if scopes is not None
            else [Scope.WEBHOOKS_MANAGE, Scope.SALES_READ, Scope.STOCK_READ],
            branch_ids,
        )
        return self.clients.create(client)

    def create(
        self,
        *,
        url: str = URL,
        event_types: list[WebhookEventType] | None = None,
        client_id: int | None = None,
        exclude_own_changes: bool = False,
        description: str | None = None,
    ) -> dict:
        return CreateWebhookEndpointCommandHandler(
            self.endpoints,
            self.clients,
            self.guard,
            self.box,
            self.limits,
            self.audit,
        ).handle(
            CreateWebhookEndpointCommand(
                url=url,
                event_types=event_types or [WebhookEventType.SALE_CONFIRMED],
                description=description,
                exclude_own_changes=exclude_own_changes,
                integration_client_id=client_id,
            )
        )

    def update(self, endpoint_id: int, as_client_id: int | None = None, **kw) -> dict:
        values: dict[str, Any] = {
            "url": URL,
            "event_types": [WebhookEventType.SALE_CONFIRMED],
            **kw,
        }
        return UpdateWebhookEndpointCommandHandler(
            self.endpoints, self.clients, self.guard, self.audit
        ).handle(
            UpdateWebhookEndpointCommand(
                endpoint_id=endpoint_id, as_client_id=as_client_id, **values
            )
        )

    def delete(self, endpoint_id: int, as_client_id: int | None = None) -> None:
        DeleteWebhookEndpointCommandHandler(self.endpoints, self.audit).handle(
            DeleteWebhookEndpointCommand(endpoint_id, as_client_id)
        )

    def enable(self, endpoint_id: int, as_client_id: int | None = None) -> dict:
        return EnableWebhookEndpointCommandHandler(
            self.endpoints, self.clients, self.audit
        ).handle(EnableWebhookEndpointCommand(endpoint_id, as_client_id))

    def disable(self, endpoint_id: int, as_client_id: int | None = None) -> dict:
        return DisableWebhookEndpointCommandHandler(self.endpoints, self.audit).handle(
            DisableWebhookEndpointCommand(endpoint_id, as_client_id)
        )

    def disable_failing(self, endpoint_id: int) -> dict | None:
        return DisableFailingWebhookEndpointCommandHandler(
            self.endpoints, self.audit
        ).handle(DisableFailingWebhookEndpointCommand(endpoint_id))

    def disable_of_client(self, client_id: int) -> int:
        return DisableClientWebhookEndpointsCommandHandler(
            self.endpoints, self.audit
        ).handle(DisableClientWebhookEndpointsCommand(client_id))

    def rotate(self, endpoint_id: int, hours: int = 24, as_client_id=None) -> dict:
        return RotateWebhookSecretCommandHandler(
            self.endpoints, self.box, self.audit
        ).handle(RotateWebhookSecretCommand(endpoint_id, hours, as_client_id))

    def send_test(self, endpoint_id: int, as_client_id: int | None = None) -> dict:
        return SendTestWebhookCommandHandler(
            self.endpoints, self.deliveries, self.outbox
        ).handle(SendTestWebhookCommand(endpoint_id, as_client_id))

    def retry(
        self, endpoint_id: int, delivery_id: int, as_client_id: int | None = None
    ) -> dict:
        return RetryWebhookDeliveryCommandHandler(
            self.endpoints, self.deliveries
        ).handle(RetryWebhookDeliveryCommand(endpoint_id, delivery_id, as_client_id))

    def list(self, as_client_id: int | None = None) -> dict:
        return ListWebhookEndpointsQueryHandler(self.endpoints).handle(
            ListWebhookEndpointsQuery(as_client_id=as_client_id)
        )

    def get(self, endpoint_id: int, as_client_id: int | None = None) -> dict:
        return GetWebhookEndpointQueryHandler(self.endpoints).handle(
            GetWebhookEndpointQuery(endpoint_id, as_client_id)
        )

    def secret(self, endpoint_id: int, as_client_id: int | None = None) -> dict:
        return GetWebhookSecretQueryHandler(self.endpoints, self.box).handle(
            GetWebhookSecretQuery(endpoint_id, as_client_id)
        )

    def history(self, endpoint_id: int, **kw) -> dict:
        return ListWebhookDeliveriesQueryHandler(
            self.endpoints, self.deliveries, self.settings
        ).handle(ListWebhookDeliveriesQuery(endpoint_id, **kw))
