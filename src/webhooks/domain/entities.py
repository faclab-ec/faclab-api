from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from src.auth.domain.scopes import Scope
from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import InvalidValueError
from src.webhooks.domain.exceptions import (
    WebhookDeliveryPendingError,
    WebhookEndpointDisabledError,
    WebhookOwnerRequiredError,
)
from src.webhooks.domain.types import BRANCH_SCOPED, REQUIRED_SCOPE, WebhookEventType

MAX_ENDPOINTS_PER_TENANT = 20
DESCRIPTION_MAX_LENGTH = 255
URL_MAX_LENGTH = 2048

# The waits between the attempts of a delivery (PUBLIC_API.md §7.2): nine
# attempts in about three days, then it is failed
RETRY_SCHEDULE = (
    timedelta(seconds=5),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=5),
    timedelta(hours=10),
    timedelta(hours=24),
    timedelta(hours=24),
)
MAX_ATTEMPTS = len(RETRY_SCHEDULE) + 1


def retry_delay(attempts: int) -> timedelta | None:
    """The wait after `attempts` failed attempts; None once they are spent"""
    if attempts < 1 or attempts > len(RETRY_SCHEDULE):
        return None
    return RETRY_SCHEDULE[attempts - 1]


class WebhookEndpointStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class DisabledReason(StrEnum):
    # Someone disabled it (the admin or its client)
    MANUAL = "manual"
    # A delivery spent its attempts without the endpoint answering any (§7.2)
    FAILING = "failing"
    # Its integration client was revoked
    CLIENT_REVOKED = "client_revoked"


@dataclass
class WebhookEndpoint(Entity):
    """An HTTPS URL of the tenant that receives the events it subscribes to,
    signed with its secret (ADR-0009). An integration client's endpoint only
    gets what its client may read, and may skip the changes its client made
    (`exclude_own_changes`)."""

    url: str
    event_types: frozenset[WebhookEventType]
    # The secret, encrypted with the environment's master key (SecretBox)
    secret_ciphertext: str
    secret_hint: str
    description: str | None = None
    integration_client_id: int | None = None
    exclude_own_changes: bool = False
    status: WebhookEndpointStatus = WebhookEndpointStatus.ACTIVE
    disabled_reason: DisabledReason | None = None
    disabled_at: datetime | None = None
    # During a rotation the previous secret signs too, until it expires
    previous_secret_ciphertext: str | None = None
    previous_secret_expires_at: datetime | None = None
    last_success_at: datetime | None = None
    # Since when its deliveries fail without one succeeding
    failing_since: datetime | None = None
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def new(
        cls,
        url: str,
        event_types: Iterable[WebhookEventType],
        secret_ciphertext: str,
        secret_hint: str,
        description: str | None = None,
        integration_client_id: int | None = None,
        exclude_own_changes: bool = False,
    ) -> "WebhookEndpoint":
        endpoint = cls(
            url=url,
            event_types=frozenset(),
            secret_ciphertext=secret_ciphertext,
            secret_hint=secret_hint,
            integration_client_id=integration_client_id,
        )
        endpoint.configure(url, event_types, description, exclude_own_changes)
        return endpoint

    def configure(
        self,
        url: str,
        event_types: Iterable[WebhookEventType],
        description: str | None,
        exclude_own_changes: bool,
    ) -> None:
        types = frozenset(event_types)
        if not types:
            raise InvalidValueError("A webhook endpoint subscribes to some event")
        if len(url) > URL_MAX_LENGTH:
            raise InvalidValueError(f"The URL is longer than {URL_MAX_LENGTH}")
        if description is not None and len(description) > DESCRIPTION_MAX_LENGTH:
            raise InvalidValueError(
                f"The description is longer than {DESCRIPTION_MAX_LENGTH}"
            )
        if exclude_own_changes and self.integration_client_id is None:
            raise WebhookOwnerRequiredError()
        self.url = url
        self.event_types = types
        self.description = description or None
        self.exclude_own_changes = exclude_own_changes

    @property
    def is_active(self) -> bool:
        return self.status == WebhookEndpointStatus.ACTIVE

    def ensure_active(self) -> None:
        if not self.is_active:
            raise WebhookEndpointDisabledError(self.require_id())

    def enable(self) -> bool:
        """Back to receiving: its pending deliveries go on, the failed ones are
        resent by hand. False when it already was active"""
        if self.is_active:
            return False
        self.status = WebhookEndpointStatus.ACTIVE
        self.disabled_reason = None
        self.disabled_at = None
        self.failing_since = None
        return True

    def disable(self, reason: DisabledReason, now: datetime) -> bool:
        """False when it already was disabled"""
        if not self.is_active:
            return False
        self.status = WebhookEndpointStatus.DISABLED
        self.disabled_reason = reason
        self.disabled_at = now
        return True

    def rotate(
        self,
        secret_ciphertext: str,
        secret_hint: str,
        previous_expires_at: datetime,
    ) -> None:
        """A new secret; the current one keeps signing until
        `previous_expires_at` (now: right away)"""
        self.previous_secret_ciphertext = self.secret_ciphertext
        self.previous_secret_expires_at = previous_expires_at
        self.secret_ciphertext = secret_ciphertext
        self.secret_hint = secret_hint

    def signing_secrets(self, now: datetime) -> list[str]:
        """The encrypted secrets that sign a message sent now"""
        sealed = [self.secret_ciphertext]
        if (
            self.previous_secret_ciphertext is not None
            and self.previous_secret_expires_at is not None
            and self.previous_secret_expires_at > now
        ):
            sealed.append(self.previous_secret_ciphertext)
        return sealed


def should_disable(last_success_at: datetime | None, failed_since: datetime) -> bool:
    """A delivery spent its attempts (about three days): the endpoint is
    disabled when it answered none since that delivery was created"""
    return last_success_at is None or last_success_at < failed_since


@dataclass(frozen=True)
class Subscriber:
    """An active endpoint as the enqueuing sees it, with what its integration
    client (if any) may read now: its scopes and branches narrow what it gets,
    like the client's token"""

    endpoint_id: int
    event_types: frozenset[WebhookEventType]
    exclude_own_changes: bool = False
    owner_id: int | None = None
    owner_scopes: frozenset[Scope] = field(default_factory=frozenset)
    # None: every branch
    owner_branch_ids: frozenset[int] | None = None

    def wants(
        self,
        event_type: WebhookEventType,
        branch_id: int | None,
        origin_integration_id: int | None,
    ) -> bool:
        if event_type not in self.event_types:
            return False
        if self.owner_id is None:
            return True
        if REQUIRED_SCOPE[event_type] not in self.owner_scopes:
            return False
        if (
            event_type in BRANCH_SCOPED
            and self.owner_branch_ids is not None
            and (branch_id is None or branch_id not in self.owner_branch_ids)
        ):
            return False
        return not (self.exclude_own_changes and origin_integration_id == self.owner_id)


class WebhookDeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    # Its attempts were spent; it is only sent again by hand
    FAILED = "failed"


@dataclass
class WebhookDelivery(Entity):
    """A message on its way to one endpoint, with its attempts"""

    message_id: int
    endpoint_id: int
    status: WebhookDeliveryStatus = WebhookDeliveryStatus.PENDING
    attempts: int = 0
    next_attempt_at: datetime | None = None
    locked_until: datetime | None = None
    last_attempt_at: datetime | None = None
    response_status: int | None = None
    last_error: str | None = None
    duration_ms: int | None = None
    delivered_at: datetime | None = None
    # The last time it was sent again by hand: its attempts start over then
    retried_at: datetime | None = None
    id: int | None = None
    created_at: datetime | None = None

    @property
    def attempts_since(self) -> datetime | None:
        """Since when its current attempts run"""
        return self.retried_at or self.created_at

    def retry(self, now: datetime) -> None:
        """Send it again (a delivered one too: the receiver lost it), with all
        its attempts. The receiver dedupes by its `webhook-id`, the same"""
        if self.status == WebhookDeliveryStatus.PENDING:
            raise WebhookDeliveryPendingError(self.require_id())
        self.status = WebhookDeliveryStatus.PENDING
        self.attempts = 0
        self.next_attempt_at = now
        self.locked_until = None
        self.retried_at = now
