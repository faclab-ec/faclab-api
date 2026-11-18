"""Requests and responses of `/api/admin/webhook-endpoints` (S6.4)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from src.shared.infra.validators import QueryParams
from src.webhooks.domain.entities import (
    DESCRIPTION_MAX_LENGTH,
    URL_MAX_LENGTH,
    DisabledReason,
    WebhookDeliveryStatus,
    WebhookEndpointStatus,
)
from src.webhooks.domain.types import WebhookEventType

_CAMEL = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class WebhookEndpointUpdateRequest(BaseModel):
    model_config = _CAMEL

    url: str = Field(
        min_length=1,
        max_length=URL_MAX_LENGTH,
        description="HTTPS URL that receives the events, towards a public address",
    )
    event_types: list[WebhookEventType] = Field(
        min_length=1,
        max_length=len(WebhookEventType),
        description="The events it receives (PUBLIC_API.md §7.1)",
    )
    description: str | None = Field(None, max_length=DESCRIPTION_MAX_LENGTH)
    exclude_own_changes: bool = Field(
        False,
        description="Skip the events its integration client caused (needs one)",
    )


class WebhookEndpointRequest(WebhookEndpointUpdateRequest):
    integration_client_id: int | None = Field(
        None,
        ge=1,
        description="The integration client it belongs to: it only gets what the "
        "client may read. Fixed once created",
    )


class RotateWebhookSecretRequest(BaseModel):
    model_config = _CAMEL

    previous_expires_in_hours: int = Field(
        24,
        ge=0,
        le=72,
        description="Hours the current secret keeps signing next to the new one",
    )


class WebhookEndpointResponse(BaseModel):
    model_config = _CAMEL

    id: int = Field(description="Webhook endpoint ID")
    url: str
    description: str | None = None
    event_types: list[WebhookEventType]
    status: WebhookEndpointStatus = Field(description="active or disabled")
    disabled_reason: DisabledReason | None = Field(
        None,
        description="manual, failing (a delivery spent its attempts) or client_revoked",
    )
    disabled_at: datetime | None = None
    integration_client_id: int | None = Field(
        None, description="Its integration client; null: the company's"
    )
    exclude_own_changes: bool
    secret_hint: str = Field(description="The start of its secret, to recognize it")
    previous_secret_expires_at: datetime | None = Field(
        None, description="Until when the previous secret signs too (rotation)"
    )
    last_success_at: datetime | None = None
    failing_since: datetime | None = Field(
        None, description="Since when its deliveries fail without one succeeding"
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WebhookSecretResponse(BaseModel):
    model_config = _CAMEL

    secret: str = Field(description="whsec_…: the key of its signatures")
    previous_secret: str | None = Field(
        None, description="The previous one while it still signs (rotation)"
    )
    previous_expires_at: datetime | None = None


class WebhookDeliveryResponse(BaseModel):
    model_config = _CAMEL

    id: int = Field(description="Delivery ID")
    endpoint_id: int
    message_id: str = Field(description="The webhook-id header: msg_…")
    event_type: str
    occurred_at: datetime
    status: WebhookDeliveryStatus = Field(description="pending, delivered or failed")
    attempts: int
    next_attempt_at: datetime | None = None
    last_attempt_at: datetime | None = None
    response_status: int | None = Field(
        None, description="HTTP status of the last attempt"
    )
    last_error: str | None = None
    duration_ms: int | None = None
    delivered_at: datetime | None = None
    retried_at: datetime | None = Field(None, description="Last manual resend")
    created_at: datetime


class WebhookEndpointQueryParams(QueryParams):
    status: WebhookEndpointStatus | None = Field(None, description="Filter by status")


class WebhookDeliveryQueryParams(QueryParams):
    status: WebhookDeliveryStatus | None = Field(None, description="Filter by status")
    event_type: str | None = Field(
        None, max_length=64, description="Filter by event type"
    )
