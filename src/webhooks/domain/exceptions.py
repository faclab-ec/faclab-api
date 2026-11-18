"""Errors of the webhooks (S6.4). Their codes are in the public error catalog
(`src/public_api/infra/errors.py`) too."""

from src.shared.domain.exceptions import BaseError, ConflictError, ValidationError


class WebhooksDisabledError(BaseError):
    """WEBHOOKS_ENABLED=false: the rollback switch (503)"""

    error_code = "WEBHOOKS_DISABLED"

    def __init__(self):
        super().__init__("Webhooks are disabled")


class WebhookUrlNotAllowedError(ValidationError):
    """A URL the server may not call: not HTTPS, or towards a private or local
    address (SSRF, 422)"""

    error_code = "WEBHOOK_URL_NOT_ALLOWED"

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(
            f"This URL can't receive webhooks: {reason}", extra={"field": "url"}
        )


class WebhookOwnerRequiredError(ValidationError):
    """`excludeOwnChanges` needs the integration client whose changes it skips"""

    error_code = "WEBHOOK_OWNER_REQUIRED"

    def __init__(self):
        super().__init__(
            "excludeOwnChanges needs the endpoint's integration client",
            extra={"field": "excludeOwnChanges"},
        )


class WebhookOwnerNotFoundError(ValidationError):
    error_code = "REFERENCE_NOT_FOUND"

    def __init__(self, client_id: int):
        super().__init__(
            f"Integration client {client_id} not found",
            extra={"field": "integrationClientId"},
        )


class WebhookEndpointLimitReachedError(ConflictError):
    error_code = "WEBHOOK_ENDPOINT_LIMIT_REACHED"

    def __init__(self, limit: int):
        super().__init__(f"A company has at most {limit} webhook endpoints")


class WebhookEndpointDisabledError(ConflictError):
    """It gets nothing until it is enabled again"""

    error_code = "WEBHOOK_ENDPOINT_DISABLED"

    def __init__(self, endpoint_id: int):
        super().__init__(f"Webhook endpoint {endpoint_id} is disabled: enable it first")


class WebhookDeliveryPendingError(ConflictError):
    """It will be sent (again) anyway"""

    error_code = "WEBHOOK_DELIVERY_PENDING"

    def __init__(self, delivery_id: int):
        super().__init__(f"Webhook delivery {delivery_id} is still pending")
