"""Enqueuing the webhooks (S6.4, ADR-0009): a message per event and a delivery
per endpoint that wants it, in the transaction of the event, so a sale that
rolls back tells nothing and one that commits is always told. The worker sends
them (`src/webhooks/infra/dispatcher.py`)."""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from wireup import injectable

from src.shared.domain.tenant import current_tenant, require_tenant
from src.webhooks.app.ports import WebhookSettings
from src.webhooks.app.repositories import WebhookQueue
from src.webhooks.domain.types import CONTRACT_VERSION, TEST_EVENT, WebhookEventType

MESSAGE_ID_PREFIX = "msg_"


def new_message_id() -> str:
    """The `webhook-id`: the same in every attempt, the receiver dedupes by it"""
    return MESSAGE_ID_PREFIX + uuid.uuid4().hex


def utc_text(value: datetime) -> str:
    """ISO 8601 in UTC with `Z` and milliseconds, like the public API. A time
    without zone is UTC already"""
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.isoformat(timespec="milliseconds") + "Z"


@injectable(lifetime="scoped")
class WebhookOutbox:
    def __init__(self, queue: WebhookQueue, settings: WebhookSettings):
        self.queue = queue
        self.settings = settings

    def subscribed(self, event_type: WebhookEventType) -> bool:
        """Whether some endpoint of the tenant subscribes to the type: the
        handlers skip building a payload nobody wants"""
        return self.settings.enabled and any(
            event_type in subscriber.event_types
            for subscriber in self.queue.subscribers()
        )

    def enqueue(
        self,
        event_type: WebhookEventType,
        data: dict[str, Any],
        *,
        branch_id: int | None,
        occurred_at: datetime | None = None,
        origin: int | None | Literal["context"] = "context",
    ) -> list[int]:
        """Delivers `data` to every endpoint that wants it; the ids of the
        deliveries. `origin` is the integration client whose request caused
        it: the context's by default (null for a user's or the worker's)"""
        if not self.settings.enabled:
            return []
        origin_id = self._origin(origin)
        endpoint_ids = [
            subscriber.endpoint_id
            for subscriber in self.queue.subscribers()
            if subscriber.wants(event_type, branch_id, origin_id)
        ]
        if not endpoint_ids:
            return []
        return self._write(event_type.value, data, occurred_at, origin_id, endpoint_ids)

    def send_test(self, endpoint_id: int, data: dict[str, Any]) -> int:
        """A `webhook.test` to one endpoint, whatever it subscribes to"""
        [delivery_id] = self._write(TEST_EVENT, data, None, None, [endpoint_id])
        return delivery_id

    def _origin(self, origin: int | None | Literal["context"]) -> int | None:
        if origin != "context":
            return origin
        context = current_tenant()
        return context.integration_id if context is not None else None

    def _write(
        self,
        event_type: str,
        data: dict[str, Any],
        occurred_at: datetime | None,
        origin_id: int | None,
        endpoint_ids: list[int],
    ) -> list[int]:
        tenant_id = require_tenant("enqueuing a webhook").tenant_id
        occurred = occurred_at or datetime.now(UTC)
        public_id = new_message_id()
        payload = {
            "id": public_id,
            "type": event_type,
            "version": CONTRACT_VERSION,
            "occurredAt": utc_text(occurred),
            "tenantId": str(tenant_id),
            "originClientId": (
                self.queue.client_public_id(origin_id)
                if origin_id is not None
                else None
            ),
            "data": data,
        }
        return self.queue.enqueue(
            public_id, event_type, payload, occurred, origin_id, endpoint_ids
        )
