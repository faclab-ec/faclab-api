"""The error catalog of the public API (S6.3, PUBLIC_API.md §4).

`/api/v1` reuses the commands of the internal API, whose error codes change
with it. An integration only ever gets a code of this catalog: any other one is
translated, a few to the public name of the same case and the rest to the
generic code of its status, and the original goes to the log. A new code
enters the catalog when an endpoint documents it.
"""

import structlog

logger = structlog.get_logger(__name__)

PUBLIC_ERROR_CODES = frozenset(
    {
        # Generic, by status
        "BUSINESS_RULE_VIOLATION",
        "CONFLICT",
        "INTERNAL_ERROR",
        "NOT_FOUND",
        "SERVICE_UNAVAILABLE",
        "VALIDATION_ERROR",
        # Credentials, scopes and branches
        "BRANCH_ACCESS_DENIED",
        "BRANCH_REQUIRED",
        "INSUFFICIENT_SCOPE",
        "INVALID_BRANCH_HEADER",
        "INVALID_TOKEN",
        "PERMISSION_DENIED",
        "TOKEN_EXPIRED",
        # The API itself
        "PUBLIC_API_DISABLED",
        "RATE_LIMITED",
        # Idempotency-Key
        "IDEMPOTENCY_IN_PROGRESS",
        "IDEMPOTENCY_KEY_REQUIRED",
        "IDEMPOTENCY_KEY_REUSED",
        "INVALID_IDEMPOTENCY_KEY",
        # References and uniqueness
        "ALREADY_EXISTS",
        "RECORD_IN_USE",
        "REFERENCE_NOT_FOUND",
        # Products
        "CONSTRUCTION_MATERIAL_TAX_MISMATCH",
        "PRODUCT_BARCODE_ALREADY_EXISTS",
        "PRODUCT_SKU_ALREADY_EXISTS",
        # Customers
        "CUSTOMER_ALREADY_EXISTS",
        "CUSTOMER_INACTIVE",
        # Sales
        "BRANCH_INACTIVE",
        "CREDIT_NOTE_REQUIRED",
        "EMISSION_POINT_INACTIVE",
        "EMISSION_POINT_OUTSIDE_BRANCH",
        "INSUFFICIENT_PAYMENT",
        "INSUFFICIENT_STOCK",
        "INVALID_SALE_STATUS",
        "INVOICE_IN_PROGRESS",
        "LOCATION_INACTIVE",
        "LOCATION_OUTSIDE_BRANCH",
        "OVERRIDE_REASON_REQUIRED",
        "PAYMENT_EXCEEDS_BALANCE",
        "PAYMENT_METHOD_NOT_ALLOWED",
        "PRESENTATION_INACTIVE",
        "PRODUCT_WITHOUT_PRICE",
        "QUANTITY_PRECISION_EXCEEDED",
        # Webhooks (S6.4)
        "INTEGRATION_CLIENT_REVOKED",
        "WEBHOOK_DELIVERY_PENDING",
        "WEBHOOK_ENDPOINT_DISABLED",
        "WEBHOOK_ENDPOINT_LIMIT_REACHED",
        "WEBHOOK_URL_NOT_ALLOWED",
        "WEBHOOKS_DISABLED",
        # The tenant's plan and subscription (S8.4)
        "PLAN_LIMIT_REACHED",
        "SUBSCRIPTION_READ_ONLY",
    }
)

# Internal codes with a public name for the same case
RENAMED = {
    "CUSTOMER_TAX_ID_ALREADY_EXISTS": "CUSTOMER_ALREADY_EXISTS",
    "INTEGRATION_NOT_ALLOWED": "PERMISSION_DENIED",
    "TENANT_REQUIRED": "INVALID_TOKEN",
    "HTTP_ERROR": "NOT_FOUND",
}

GENERIC_BY_STATUS = {
    400: "BUSINESS_RULE_VIOLATION",
    401: "INVALID_TOKEN",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}


def public_error_code(code: str, status: int) -> str:
    """The code an integration gets for an internal error code"""
    if code in PUBLIC_ERROR_CODES:
        return code
    public = RENAMED.get(code)
    if public is None or (code == "HTTP_ERROR" and status != 404):
        public = GENERIC_BY_STATUS.get(
            status, "INTERNAL_ERROR" if status >= 500 else "BUSINESS_RULE_VIOLATION"
        )
    logger.info("public_api_error_translated", error_code=code, public_code=public)
    return public
