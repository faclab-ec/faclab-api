from wireup import injectable

from config import config
from src.webhooks.app.commands.endpoints import (
    CreateWebhookEndpointCommandHandler,
    DeleteWebhookEndpointCommandHandler,
    DisableClientWebhookEndpointsCommandHandler,
    DisableFailingWebhookEndpointCommandHandler,
    DisableWebhookEndpointCommandHandler,
    EnableWebhookEndpointCommandHandler,
    RetryWebhookDeliveryCommandHandler,
    RotateWebhookSecretCommandHandler,
    SendTestWebhookCommandHandler,
    UpdateWebhookEndpointCommandHandler,
)
from src.webhooks.app.outbox import WebhookOutbox
from src.webhooks.app.ports import WebhookSettings
from src.webhooks.app.queries.endpoints import (
    GetWebhookEndpointQueryHandler,
    GetWebhookSecretQueryHandler,
    ListWebhookDeliveriesQueryHandler,
    ListWebhookEndpointsQueryHandler,
)
from src.webhooks.infra.mappers import WebhookDeliveryMapper, WebhookEndpointMapper
from src.webhooks.infra.repositories import (
    SqlAlchemyWebhookDeliveryRepository,
    SqlAlchemyWebhookEndpointRepository,
    SqlAlchemyWebhookQueue,
)
from src.webhooks.infra.secrets import secret_box
from src.webhooks.infra.urls import webhook_url_policy


@injectable(lifetime="singleton")
def webhook_settings() -> WebhookSettings:
    return WebhookSettings(
        enabled=config.WEBHOOKS_ENABLED, retention_days=config.WEBHOOK_RETENTION_DAYS
    )


INJECTABLES = [
    webhook_settings,
    secret_box,
    webhook_url_policy,
    WebhookEndpointMapper,
    WebhookDeliveryMapper,
    SqlAlchemyWebhookEndpointRepository,
    SqlAlchemyWebhookDeliveryRepository,
    SqlAlchemyWebhookQueue,
    WebhookOutbox,
    CreateWebhookEndpointCommandHandler,
    UpdateWebhookEndpointCommandHandler,
    DeleteWebhookEndpointCommandHandler,
    EnableWebhookEndpointCommandHandler,
    DisableWebhookEndpointCommandHandler,
    DisableFailingWebhookEndpointCommandHandler,
    DisableClientWebhookEndpointsCommandHandler,
    RotateWebhookSecretCommandHandler,
    SendTestWebhookCommandHandler,
    RetryWebhookDeliveryCommandHandler,
    ListWebhookEndpointsQueryHandler,
    GetWebhookEndpointQueryHandler,
    GetWebhookSecretQueryHandler,
    ListWebhookDeliveriesQueryHandler,
]
