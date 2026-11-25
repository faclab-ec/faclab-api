"""The tenant's webhook endpoints (S6.4). The admin manages every one
(`/api/admin/webhook-endpoints`); an integration client only its own
(`/api/v1/webhook-endpoints`): `as_client_id` names it, and an endpoint of
another one is not found."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from wireup import injectable

from src.auth.domain.exceptions import InsufficientScopeError
from src.integrations.app.repositories import IntegrationClientRepository
from src.integrations.domain.exceptions import IntegrationClientRevokedError
from src.shared.app.audit import AuditAction, AuditTrail, changed
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.plans import PlanLimits, PlanResource
from src.shared.domain.exceptions import NotFoundError
from src.webhooks.app.outbox import WebhookOutbox
from src.webhooks.app.ports import SecretBox, WebhookUrlPolicy
from src.webhooks.app.repositories import (
    WebhookDeliveryRepository,
    WebhookEndpointRepository,
)
from src.webhooks.app.views import describe_endpoint, redacted_url
from src.webhooks.domain.entities import (
    MAX_ENDPOINTS_PER_TENANT,
    DisabledReason,
    WebhookEndpoint,
)
from src.webhooks.domain.exceptions import (
    WebhookEndpointLimitReachedError,
    WebhookOwnerNotFoundError,
)
from src.webhooks.domain.signing import new_secret, secret_hint
from src.webhooks.domain.types import WebhookEventType, missing_scopes

# How long the previous secret keeps signing after a rotation, by default
ROTATION_OVERLAP_HOURS = 24
TEST_MESSAGE = "A test event of Faclab: if you can read this, your endpoint works"


def audited(endpoint: WebhookEndpoint) -> dict:
    """What the audit log keeps of an endpoint: never its secret, and its URL
    without the query"""
    return {
        "url": redacted_url(endpoint.url),
        "event_types": sorted(endpoint.event_types),
        "description": endpoint.description,
        "exclude_own_changes": endpoint.exclude_own_changes,
    }


def get_endpoint(
    endpoints: WebhookEndpointRepository,
    endpoint_id: int,
    as_client_id: int | None,
    for_update: bool = False,
) -> WebhookEndpoint:
    endpoint = (
        endpoints.first_for_update(id=endpoint_id)
        if for_update
        else endpoints.get_by_id(endpoint_id)
    )
    if endpoint is None or (
        as_client_id is not None and endpoint.integration_client_id != as_client_id
    ):
        raise NotFoundError(f"Webhook endpoint {endpoint_id} not found")
    return endpoint


def ensure_owner(
    clients: IntegrationClientRepository,
    owner_id: int | None,
    event_types: Iterable[WebhookEventType],
) -> None:
    """An integration client's endpoint only subscribes to what its client may
    read through the API"""
    if owner_id is None:
        return
    client = clients.get_by_id(owner_id)
    if client is None:
        raise WebhookOwnerNotFoundError(owner_id)
    if not client.is_active:
        raise IntegrationClientRevokedError()
    missing = missing_scopes(frozenset(event_types), client.scopes)
    if missing:
        raise InsufficientScopeError(missing)


@dataclass
class CreateWebhookEndpointCommand(Command):
    url: str
    event_types: list[WebhookEventType] = field(default_factory=list)
    description: str | None = None
    exclude_own_changes: bool = False
    # Its integration client: the one calling /api/v1, or the one the admin names
    integration_client_id: int | None = None


@injectable(lifetime="scoped")
class CreateWebhookEndpointCommandHandler(
    CommandHandler[CreateWebhookEndpointCommand, dict]
):
    """An endpoint with a new secret, read with `GET …/{id}/secret`. It takes
    a seat of the plan (S8.4), under the platform's cap of 20"""

    def __init__(
        self,
        endpoints: WebhookEndpointRepository,
        clients: IntegrationClientRepository,
        policy: WebhookUrlPolicy,
        box: SecretBox,
        limits: PlanLimits,
        audit: AuditTrail,
    ):
        self.endpoints = endpoints
        self.clients = clients
        self.policy = policy
        self.box = box
        self.limits = limits
        self.audit = audit

    def _handle(self, command: CreateWebhookEndpointCommand) -> dict:
        # First: it waits for a concurrent creation of the tenant to end
        self.limits.ensure_room(PlanResource.WEBHOOK_ENDPOINTS)
        if self.endpoints.count_by() >= MAX_ENDPOINTS_PER_TENANT:
            raise WebhookEndpointLimitReachedError(MAX_ENDPOINTS_PER_TENANT)
        ensure_owner(self.clients, command.integration_client_id, command.event_types)
        self.policy.ensure_allowed(command.url)
        secret = new_secret()
        endpoint = self.endpoints.create(
            WebhookEndpoint.new(
                command.url,
                command.event_types,
                self.box.seal(secret),
                secret_hint(secret),
                description=command.description,
                integration_client_id=command.integration_client_id,
                exclude_own_changes=command.exclude_own_changes,
            )
        )
        self.audit.record(
            AuditAction.WEBHOOK_ENDPOINT_CREATED,
            endpoint.require_id(),
            after={
                **audited(endpoint),
                "integration_client_id": endpoint.integration_client_id,
            },
        )
        return describe_endpoint(endpoint)


@dataclass
class UpdateWebhookEndpointCommand(Command):
    endpoint_id: int
    url: str
    event_types: list[WebhookEventType] = field(default_factory=list)
    description: str | None = None
    exclude_own_changes: bool = False
    as_client_id: int | None = None


@injectable(lifetime="scoped")
class UpdateWebhookEndpointCommandHandler(
    CommandHandler[UpdateWebhookEndpointCommand, dict]
):
    """Its URL (checked again), events, description and `exclude_own_changes`.
    Its integration client stays: it is fixed when the endpoint is created"""

    def __init__(
        self,
        endpoints: WebhookEndpointRepository,
        clients: IntegrationClientRepository,
        policy: WebhookUrlPolicy,
        audit: AuditTrail,
    ):
        self.endpoints = endpoints
        self.clients = clients
        self.policy = policy
        self.audit = audit

    def _handle(self, command: UpdateWebhookEndpointCommand) -> dict:
        endpoint = get_endpoint(
            self.endpoints, command.endpoint_id, command.as_client_id, for_update=True
        )
        previous = audited(endpoint)
        ensure_owner(self.clients, endpoint.integration_client_id, command.event_types)
        self.policy.ensure_allowed(command.url)
        endpoint.configure(
            command.url,
            command.event_types,
            command.description,
            command.exclude_own_changes,
        )
        endpoint = self.endpoints.update(endpoint)
        before, after = changed(previous, audited(endpoint))
        if after:
            self.audit.record(
                AuditAction.WEBHOOK_ENDPOINT_UPDATED,
                endpoint.require_id(),
                before=before,
                after=after,
            )
        return describe_endpoint(endpoint)


@dataclass
class DeleteWebhookEndpointCommand(Command):
    endpoint_id: int
    as_client_id: int | None = None


@injectable(lifetime="scoped")
class DeleteWebhookEndpointCommandHandler(
    CommandHandler[DeleteWebhookEndpointCommand, None]
):
    """For good, with its deliveries: what was on its way is not sent"""

    def __init__(self, endpoints: WebhookEndpointRepository, audit: AuditTrail):
        self.endpoints = endpoints
        self.audit = audit

    def _handle(self, command: DeleteWebhookEndpointCommand) -> None:
        endpoint = get_endpoint(
            self.endpoints, command.endpoint_id, command.as_client_id, for_update=True
        )
        self.endpoints.remove(endpoint.require_id())
        self.audit.record(
            AuditAction.WEBHOOK_ENDPOINT_DELETED,
            endpoint.require_id(),
            before={
                **audited(endpoint),
                "integration_client_id": endpoint.integration_client_id,
            },
        )


@dataclass
class EnableWebhookEndpointCommand(Command):
    endpoint_id: int
    as_client_id: int | None = None


@injectable(lifetime="scoped")
class EnableWebhookEndpointCommandHandler(
    CommandHandler[EnableWebhookEndpointCommand, dict]
):
    """Back to receiving: its pending deliveries go on, the failed ones are
    sent again by hand (`…/deliveries/{id}/retry`)"""

    def __init__(
        self,
        endpoints: WebhookEndpointRepository,
        clients: IntegrationClientRepository,
        audit: AuditTrail,
    ):
        self.endpoints = endpoints
        self.clients = clients
        self.audit = audit

    def _handle(self, command: EnableWebhookEndpointCommand) -> dict:
        endpoint = get_endpoint(
            self.endpoints, command.endpoint_id, command.as_client_id, for_update=True
        )
        before = {
            "status": endpoint.status,
            "disabled_reason": endpoint.disabled_reason,
        }
        if endpoint.integration_client_id is not None:
            ensure_owner(
                self.clients, endpoint.integration_client_id, endpoint.event_types
            )
        if endpoint.enable():
            endpoint = self.endpoints.update(endpoint)
            self.audit.record(
                AuditAction.WEBHOOK_ENDPOINT_ENABLED,
                endpoint.require_id(),
                before=before,
                after={"status": endpoint.status},
            )
        return describe_endpoint(endpoint)


@dataclass
class DisableWebhookEndpointCommand(Command):
    endpoint_id: int
    as_client_id: int | None = None


@injectable(lifetime="scoped")
class DisableWebhookEndpointCommandHandler(
    CommandHandler[DisableWebhookEndpointCommand, dict]
):
    """It stops receiving; what it had pending waits until it is enabled"""

    def __init__(self, endpoints: WebhookEndpointRepository, audit: AuditTrail):
        self.endpoints = endpoints
        self.audit = audit

    def _handle(self, command: DisableWebhookEndpointCommand) -> dict:
        endpoint = get_endpoint(
            self.endpoints, command.endpoint_id, command.as_client_id, for_update=True
        )
        return disable(self.endpoints, self.audit, endpoint, DisabledReason.MANUAL)


@dataclass
class DisableFailingWebhookEndpointCommand(Command):
    endpoint_id: int


@injectable(lifetime="scoped")
class DisableFailingWebhookEndpointCommandHandler(
    CommandHandler[DisableFailingWebhookEndpointCommand, dict | None]
):
    """The worker's, when a delivery spent its attempts without the endpoint
    answering any (PUBLIC_API.md §7.2). None when it already was disabled"""

    def __init__(self, endpoints: WebhookEndpointRepository, audit: AuditTrail):
        self.endpoints = endpoints
        self.audit = audit

    def _handle(self, command: DisableFailingWebhookEndpointCommand) -> dict | None:
        endpoint = self.endpoints.first_for_update(id=command.endpoint_id)
        if endpoint is None or not endpoint.is_active:
            return None
        return disable(self.endpoints, self.audit, endpoint, DisabledReason.FAILING)


@dataclass
class DisableClientWebhookEndpointsCommand(Command):
    integration_client_id: int


@injectable(lifetime="scoped")
class DisableClientWebhookEndpointsCommandHandler(
    CommandHandler[DisableClientWebhookEndpointsCommand, int]
):
    """A revoked integration client's endpoints stop receiving; how many"""

    def __init__(self, endpoints: WebhookEndpointRepository, audit: AuditTrail):
        self.endpoints = endpoints
        self.audit = audit

    def _handle(self, command: DisableClientWebhookEndpointsCommand) -> int:
        disabled = 0
        for endpoint in self.endpoints.of_owner(command.integration_client_id):
            if endpoint.is_active:
                disable(
                    self.endpoints, self.audit, endpoint, DisabledReason.CLIENT_REVOKED
                )
                disabled += 1
        return disabled


def disable(
    endpoints: WebhookEndpointRepository,
    audit: AuditTrail,
    endpoint: WebhookEndpoint,
    reason: DisabledReason,
) -> dict:
    if endpoint.disable(reason, datetime.now()):
        endpoint = endpoints.update(endpoint)
        audit.record(
            AuditAction.WEBHOOK_ENDPOINT_DISABLED,
            endpoint.require_id(),
            before={"status": "active"},
            after={"status": endpoint.status, "disabled_reason": reason},
        )
    return describe_endpoint(endpoint)


@dataclass
class RotateWebhookSecretCommand(Command):
    endpoint_id: int
    previous_expires_in_hours: int = ROTATION_OVERLAP_HOURS
    as_client_id: int | None = None


@injectable(lifetime="scoped")
class RotateWebhookSecretCommandHandler(
    CommandHandler[RotateWebhookSecretCommand, dict]
):
    """A new secret; the current one keeps signing next to it (two signatures
    in the header) for `previous_expires_in_hours`, 0 = no more"""

    def __init__(
        self, endpoints: WebhookEndpointRepository, box: SecretBox, audit: AuditTrail
    ):
        self.endpoints = endpoints
        self.box = box
        self.audit = audit

    def _handle(self, command: RotateWebhookSecretCommand) -> dict:
        endpoint = get_endpoint(
            self.endpoints, command.endpoint_id, command.as_client_id, for_update=True
        )
        secret = new_secret()
        expires_at = datetime.now() + timedelta(hours=command.previous_expires_in_hours)
        endpoint.rotate(self.box.seal(secret), secret_hint(secret), expires_at)
        endpoint = self.endpoints.update(endpoint)
        self.audit.record(
            AuditAction.WEBHOOK_ENDPOINT_SECRET_ROTATED,
            endpoint.require_id(),
            after={"previous_expires_at": expires_at},
        )
        return describe_endpoint(endpoint)


@dataclass
class SendTestWebhookCommand(Command):
    endpoint_id: int
    as_client_id: int | None = None


@injectable(lifetime="scoped")
class SendTestWebhookCommandHandler(CommandHandler[SendTestWebhookCommand, dict]):
    """Queues a `webhook.test` to the endpoint; the worker sends it like any
    other. Its delivery, pending"""

    def __init__(
        self,
        endpoints: WebhookEndpointRepository,
        deliveries: WebhookDeliveryRepository,
        outbox: WebhookOutbox,
    ):
        self.endpoints = endpoints
        self.deliveries = deliveries
        self.outbox = outbox

    def _handle(self, command: SendTestWebhookCommand) -> dict:
        endpoint = get_endpoint(
            self.endpoints, command.endpoint_id, command.as_client_id
        )
        endpoint.ensure_active()
        delivery_id = self.outbox.send_test(
            endpoint.require_id(),
            {"endpointId": endpoint.require_id(), "message": TEST_MESSAGE},
        )
        return describe_delivery(self.deliveries, delivery_id)


@dataclass
class RetryWebhookDeliveryCommand(Command):
    endpoint_id: int
    delivery_id: int
    as_client_id: int | None = None


@injectable(lifetime="scoped")
class RetryWebhookDeliveryCommandHandler(
    CommandHandler[RetryWebhookDeliveryCommand, dict]
):
    """Sends a delivered or failed delivery again, with its attempts from the
    start and the same `webhook-id`"""

    def __init__(
        self,
        endpoints: WebhookEndpointRepository,
        deliveries: WebhookDeliveryRepository,
    ):
        self.endpoints = endpoints
        self.deliveries = deliveries

    def _handle(self, command: RetryWebhookDeliveryCommand) -> dict:
        endpoint = get_endpoint(
            self.endpoints, command.endpoint_id, command.as_client_id
        )
        endpoint.ensure_active()
        delivery = self.deliveries.first_for_update(
            id=command.delivery_id, endpoint_id=endpoint.require_id()
        )
        if delivery is None:
            raise NotFoundError(f"Webhook delivery {command.delivery_id} not found")
        delivery.retry(datetime.now())
        self.deliveries.update(delivery)
        return describe_delivery(self.deliveries, delivery.require_id())


def describe_delivery(deliveries: WebhookDeliveryRepository, delivery_id: int) -> dict:
    described = deliveries.describe(delivery_id)
    if described is None:
        raise NotFoundError(f"Webhook delivery {delivery_id} not found")
    return described
