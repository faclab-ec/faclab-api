from typing import Any, overload

from wireup import injectable

from src.shared.infra.mappers import Mapper
from src.webhooks.domain.entities import (
    DisabledReason,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEndpointStatus,
)
from src.webhooks.domain.types import WebhookEventType
from src.webhooks.infra.models import WebhookDeliveryModel, WebhookEndpointModel


@injectable(lifetime="singleton")
class WebhookEndpointMapper(Mapper[WebhookEndpoint, WebhookEndpointModel]):
    """By hand: its events are a set in the entity and a JSON list in the table"""

    __entity__ = WebhookEndpoint

    @overload
    def to_entity(self, model: WebhookEndpointModel) -> WebhookEndpoint: ...

    @overload
    def to_entity(self, model: None) -> None: ...

    def to_entity(self, model: WebhookEndpointModel | None) -> WebhookEndpoint | None:
        if model is None:
            return None
        return WebhookEndpoint(
            id=model.id,
            url=model.url,
            description=model.description,
            # A type retired from the catalog stops counting
            event_types=frozenset(
                WebhookEventType(name)
                for name in model.event_types
                if name in WebhookEventType._value2member_map_
            ),
            status=WebhookEndpointStatus(model.status),
            disabled_reason=(
                DisabledReason(model.disabled_reason) if model.disabled_reason else None
            ),
            disabled_at=model.disabled_at,
            integration_client_id=model.integration_client_id,
            exclude_own_changes=model.exclude_own_changes,
            secret_ciphertext=model.secret_ciphertext,
            secret_hint=model.secret_hint,
            previous_secret_ciphertext=model.previous_secret_ciphertext,
            previous_secret_expires_at=model.previous_secret_expires_at,
            last_success_at=model.last_success_at,
            failing_since=model.failing_since,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def to_dict(self, entity: WebhookEndpoint) -> dict[str, Any]:
        values: dict[str, Any] = {
            "url": entity.url,
            "description": entity.description,
            "event_types": sorted(t.value for t in entity.event_types),
            "status": entity.status.value,
            "disabled_reason": (
                entity.disabled_reason.value if entity.disabled_reason else None
            ),
            "disabled_at": entity.disabled_at,
            "integration_client_id": entity.integration_client_id,
            "exclude_own_changes": entity.exclude_own_changes,
            "secret_ciphertext": entity.secret_ciphertext,
            "secret_hint": entity.secret_hint,
            "previous_secret_ciphertext": entity.previous_secret_ciphertext,
            "previous_secret_expires_at": entity.previous_secret_expires_at,
            "last_success_at": entity.last_success_at,
            "failing_since": entity.failing_since,
        }
        if entity.id is not None:
            values["id"] = entity.id
        return values


@injectable(lifetime="singleton")
class WebhookDeliveryMapper(Mapper[WebhookDelivery, WebhookDeliveryModel]):
    __entity__ = WebhookDelivery
    __exclude_fields__ = frozenset({"created_at"})
