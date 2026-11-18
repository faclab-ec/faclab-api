from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.public_api.app.listing import DEFAULT_LIMIT, MAX_LIMIT
from src.public_api.infra.schemas.base import PublicInput, PublicModel
from src.public_api.infra.types import Timestamp
from src.webhooks.domain.entities import (
    DESCRIPTION_MAX_LENGTH,
    URL_MAX_LENGTH,
    DisabledReason,
    WebhookDeliveryStatus,
    WebhookEndpointStatus,
)
from src.webhooks.domain.types import WebhookEventType


class WebhookEndpoint(PublicModel):
    id: int
    url: str
    description: str | None = None
    event_types: list[WebhookEventType]
    status: WebhookEndpointStatus
    disabled_reason: DisabledReason | None = Field(
        None,
        description="`manual`, `failing` (a delivery spent its attempts without "
        "an answer) or `client_revoked`",
    )
    disabled_at: Timestamp | None = None
    exclude_own_changes: bool = Field(
        description="It skips the events this client's own requests caused"
    )
    secret_hint: str = Field(description="The start of its secret, to recognize it")
    previous_secret_expires_at: Timestamp | None = Field(
        None, description="Until when the previous secret signs too (rotation)"
    )
    last_success_at: Timestamp | None = None
    failing_since: Timestamp | None = Field(
        None, description="Since when its deliveries fail without one succeeding"
    )
    created_at: Timestamp
    updated_at: Timestamp


class WebhookSecret(PublicModel):
    secret: str = Field(
        description="`whsec_` and the base64 of the HMAC-SHA256 key of its signatures"
    )
    previous_secret: str | None = Field(
        None, description="The previous one while it still signs (rotation)"
    )
    previous_expires_at: Timestamp | None = None


class WebhookDelivery(PublicModel):
    id: int
    message_id: str = Field(description="Its `webhook-id`: `msg_…`")
    event_type: str
    occurred_at: Timestamp
    status: WebhookDeliveryStatus
    attempts: int = Field(description="Attempts since it was created or resent")
    next_attempt_at: Timestamp | None = None
    last_attempt_at: Timestamp | None = None
    response_status: int | None = Field(
        None, description="HTTP status the endpoint answered last"
    )
    last_error: str | None = None
    duration_ms: int | None = None
    delivered_at: Timestamp | None = None
    retried_at: Timestamp | None = Field(None, description="Last manual resend")
    created_at: Timestamp


class WebhookEndpointInput(PublicInput):
    url: str = Field(
        min_length=1,
        max_length=URL_MAX_LENGTH,
        description="HTTPS URL towards a public address",
    )
    event_types: list[WebhookEventType] = Field(
        min_length=1,
        max_length=len(WebhookEventType),
        description="What it receives; each needs the read scope of its resource",
    )
    description: str | None = Field(None, max_length=DESCRIPTION_MAX_LENGTH)
    exclude_own_changes: bool = Field(
        False, description="Skip the events this client's own requests caused"
    )


class RotateWebhookSecretInput(PublicInput):
    previous_expires_in_hours: int = Field(
        24,
        ge=0,
        le=72,
        description="Hours the current secret keeps signing next to the new one",
    )


class _Page(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    limit: int = Field(
        DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Page size (1-200)"
    )
    offset: int = Field(0, ge=0, description="Rows to skip")


class WebhookEndpointListParams(_Page):
    status: WebhookEndpointStatus | None = None


class WebhookDeliveryListParams(_Page):
    status: WebhookDeliveryStatus | None = None
    event_type: str | None = Field(None, max_length=64)
