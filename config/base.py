from dataclasses import dataclass
from decimal import Decimal

from environs import Env

env = Env()


@dataclass
class OpenTelemetryConfig:
    service_name: str
    service_version: str
    otlp_endpoint: str
    environment: str
    enabled: bool = True
    sampling_rate: float = 1.0
    # Plain-text OTLP; only for local, where the collector has no TLS
    insecure: bool = False


@dataclass
class DocsConfig:
    title: str
    version: str
    description: str
    openapi_tags: list[dict]
    tag_groups: list[dict]
    enabled: bool = True


class BaseConfig:
    SERVICE_NAME = env("SERVICE_NAME", "faclab-core")
    # Set at build time (tag or commit SHA); reported in every log and span
    SERVICE_VERSION = env("SERVICE_VERSION", "dev")
    ENVIRONMENT = env("ENVIRONMENT", "local")

    #
    # Logging config
    #
    LOG_LEVEL = env("LOG_LEVEL", "INFO")

    #
    # Database config (required outside local). The API connects as faclab_app,
    # under row-level security; DATABASE_URL_WORKER is faclab_worker, which
    # bypasses it, for the outbox relay and the platform lookups that run
    # outside every tenant (S2.4)
    #
    DB_CONNECTION_STRING = env.str("DATABASE_URL", "")
    DB_WORKER_URL = env.str("DATABASE_URL_WORKER", "")

    #
    # CORS: comma-separated origins allowed to call the API (required outside local)
    #
    CORS_ORIGINS: list[str] = env.list("CORS_ORIGINS", [])

    #
    # OpenTelemetry config
    #
    OTEL_OTLP_ENDPOINT = env("OTEL_OTLP_ENDPOINT", "http://localhost:4317")
    OTEL_SERVICE_NAME = env("OTEL_SERVICE_NAME", SERVICE_NAME)
    OTEL_ENVIRONMENT = env("OTEL_ENVIRONMENT", ENVIRONMENT)
    OTEL_ENABLED = env.bool("OTEL_ENABLED", True)
    OTEL_SAMPLING_RATE = env.float("OTEL_SAMPLING_RATE", 1.0)
    OTEL_EXPORTER_OTLP_INSECURE = env.bool("OTEL_EXPORTER_OTLP_INSECURE", False)

    #
    # Kafka config
    #
    KAFKA_BOOTSTRAP_SERVERS = env("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    KAFKA_ENABLED = env.bool("KAFKA_ENABLED", False)
    # How often the outbox relay looks for unpublished messages; in the API
    # (RUN_BACKGROUND) it also wakes up right after a commit that wrote one
    OUTBOX_POLL_INTERVAL_SECONDS = env.float("OUTBOX_POLL_INTERVAL_SECONDS", 1.0)
    # A message that fails this many times is `failed` and stops holding back
    # its tenant's next ones; between attempts it waits BASE * 2^(n-1) seconds,
    # up to MAX. A broker outage counts no attempt
    OUTBOX_MAX_ATTEMPTS = env.int("OUTBOX_MAX_ATTEMPTS", 10)
    OUTBOX_RETRY_BASE_SECONDS = env.float("OUTBOX_RETRY_BASE_SECONDS", 5.0)
    OUTBOX_RETRY_MAX_SECONDS = env.float("OUTBOX_RETRY_MAX_SECONDS", 600.0)
    # Published messages are kept this long (to look at or send again)
    OUTBOX_RETENTION_DAYS = env.int("OUTBOX_RETENTION_DAYS", 14)
    # Consumer group for the topics core reads (invoice results); every replica
    # shares it so each message is handled once
    KAFKA_CONSUMER_GROUP_ID = env("KAFKA_CONSUMER_GROUP_ID", "faclab-core")
    # A message whose handler fails this many times (waiting BASE * 2^(n-1)
    # seconds between them, up to a minute) goes to dead_letters
    KAFKA_CONSUMER_MAX_ATTEMPTS = env.int("KAFKA_CONSUMER_MAX_ATTEMPTS", 5)
    KAFKA_CONSUMER_RETRY_BASE_SECONDS = env.float(
        "KAFKA_CONSUMER_RETRY_BASE_SECONDS", 2.0
    )

    #
    # Background work (S3.4): the worker process (`python worker.py`) runs the
    # messaging and the purges. RUN_BACKGROUND=true also starts the messaging
    # in the API, as before the worker (rollback switch)
    #
    RUN_BACKGROUND = env.bool("RUN_BACKGROUND", True)
    WORKER_PURGE_INTERVAL_SECONDS = env.float("WORKER_PURGE_INTERVAL_SECONDS", 3600.0)
    # Last successful cycle of each task, read by the container's health check
    WORKER_HEALTH_FILE = env.str("WORKER_HEALTH_FILE", "/tmp/faclab-worker-health.json")
    # Credit notes (S4.5, only with KAFKA_ENABLED): false stops asking for them, the
    # ones issued are kept (the rollback switch). An invoice to the final consumer
    # admits none (NAC-DGERCGC25-00000014, art. 3), so such a refund is refused;
    # true lets it through, as an internal refund without a credit note (D-4).
    CREDIT_NOTES_ENABLED = env.bool("CREDIT_NOTES_ENABLED", True)
    FINAL_CONSUMER_REFUNDS_ALLOWED = env.bool("FINAL_CONSUMER_REFUNDS_ALLOWED", False)

    # Shift closing (S5.9): a difference between what was counted and what was
    # expected of a payment method needs a justification when it is over this
    # amount (absolute value; 0 = any difference). Each Z closing keeps the one it
    # was closed with
    SHIFT_CLOSING_JUSTIFICATION_THRESHOLD = env.decimal(
        "SHIFT_CLOSING_JUSTIFICATION_THRESHOLD",
        Decimal("1.00"),
        validate=lambda value: value >= 0,
    )

    # Reconciliation with faclab-invoicing (S4.3, only with KAFKA_ENABLED): every
    # INTERVAL it opens a discrepancy for each confirmed sale still without an
    # invoice result PENDING_MINUTES after it was sent. ENABLED=false turns it off
    INVOICE_RECONCILIATION_ENABLED = env.bool("INVOICE_RECONCILIATION_ENABLED", True)
    INVOICE_RECONCILIATION_INTERVAL_SECONDS = env.float(
        "INVOICE_RECONCILIATION_INTERVAL_SECONDS", 300.0
    )
    INVOICE_RECONCILIATION_PENDING_MINUTES = env.int(
        "INVOICE_RECONCILIATION_PENDING_MINUTES", 30
    )

    #
    # Email (S5.4): quotes go out as PDF through any SMTP server. Off unless
    # enabled; then SMTP_HOST and EMAIL_FROM (the platform's address, the
    # message carries the company's name) are required. SMTP_SECURE is SMTPS
    # (port 465); otherwise STARTTLS, required unless SMTP_REQUIRE_TLS=false
    #
    EMAIL_ENABLED = env.bool("EMAIL_ENABLED", False)
    EMAIL_FROM = env.str("EMAIL_FROM", "")
    SMTP_HOST = env.str("SMTP_HOST", "")
    SMTP_PORT = env.int("SMTP_PORT", 587)
    SMTP_SECURE = env.bool("SMTP_SECURE", False)
    SMTP_REQUIRE_TLS = env.bool("SMTP_REQUIRE_TLS", True)
    SMTP_USER = env.str("SMTP_USER", "")
    SMTP_PASSWORD = env.str("SMTP_PASSWORD", "")
    SMTP_TIMEOUT_SECONDS = env.float("SMTP_TIMEOUT_SECONDS", 20.0)

    #
    # Auth / JWT config
    #
    # Tokens are signed with an Ed25519 key (EdDSA, S6.1) and its public part is
    # published in /.well-known/jwks.json, where other services (faclab-invoicing)
    # check them. The signing key goes as PEM (PKCS#8) in JWT_PRIVATE_KEY or in
    # the file of JWT_PRIVATE_KEY_FILE, never both. JWT_PUBLIC_KEYS(_FILE) holds
    # more public keys (PEM blocks one after the other) that are also accepted
    # and published: the previous key during a rotation, or the next one before
    # it signs. Locally, without a key, a fixed development key signs
    JWT_PRIVATE_KEY = env.str("JWT_PRIVATE_KEY", "")
    JWT_PRIVATE_KEY_FILE = env.str("JWT_PRIVATE_KEY_FILE", "")
    JWT_PUBLIC_KEYS = env.str("JWT_PUBLIC_KEYS", "")
    JWT_PUBLIC_KEYS_FILE = env.str("JWT_PUBLIC_KEYS_FILE", "")
    JWT_ACCESS_TTL_SECONDS = env.int("JWT_ACCESS_TTL_SECONDS", 900)
    JWT_REFRESH_TTL_SECONDS = env.int("JWT_REFRESH_TTL_SECONDS", 604800)
    JWT_ISSUER = env("JWT_ISSUER", "faclab-core")
    # Every token names this service in `aud`; access tokens also name the
    # other services that accept them
    JWT_AUDIENCE = env.str("JWT_AUDIENCE", "faclab-core")
    JWT_SERVICE_AUDIENCES: list[str] = env.list(
        "JWT_SERVICE_AUDIENCES", ["faclab-invoicing"]
    )
    # A refresh token used again within this many seconds after it was rotated
    # (two tabs refreshing at once, a lost response) gets the current session
    # instead of revoking it. 0 makes every reuse revoke the session
    JWT_REFRESH_REUSE_GRACE_SECONDS = env.int("JWT_REFRESH_REUSE_GRACE_SECONDS", 30)
    # A user with several tenants gets a selection token at login and trades it
    # for a session of one tenant in POST /api/auth/select-tenant
    JWT_SELECTION_TTL_SECONDS = env.int("JWT_SELECTION_TTL_SECONDS", 300)
    # Revoked or expired sessions are deleted after this many days
    AUTH_SESSION_RETENTION_DAYS = env.int("AUTH_SESSION_RETENTION_DAYS", 30)

    #
    # Integration clients (S6.2): OAuth 2.0 client credentials at
    # POST /api/oauth/token. false refuses new tokens (503) and the ones already
    # issued (rollback switch). Clients belong to the deployment's environment
    # (fl_live_ in production, fl_test_ in a sandbox) and a token is only given
    # to one of it, so the credentials of a database copied elsewhere don't
    # work there. A token checks its client's state (revoked, scopes, branches)
    # cached at most this many seconds: revoking takes effect within it
    #
    INTEGRATIONS_ENABLED = env.bool("INTEGRATIONS_ENABLED", True)
    INTEGRATION_ENVIRONMENT = env.str(
        "INTEGRATION_ENVIRONMENT",
        "sandbox",
        validate=lambda value: value in ("sandbox", "production"),
    )
    INTEGRATION_STATUS_CACHE_SECONDS = env.int(
        "INTEGRATION_STATUS_CACHE_SECONDS",
        30,
        validate=lambda value: 0 <= value <= 60,
    )

    #
    # Public API /api/v1 (S6.3): false answers 503 PUBLIC_API_DISABLED on every
    # route (rollback switch). Each integration client and each tenant has a
    # rate limit (GCRA, counters in PostgreSQL, D-6): requests per minute,
    # with bursts of up to BURST at once; over it, 429 with Retry-After
    #
    PUBLIC_API_ENABLED = env.bool("PUBLIC_API_ENABLED", True)
    PUBLIC_API_RATE_LIMIT_ENABLED = env.bool("PUBLIC_API_RATE_LIMIT_ENABLED", True)
    PUBLIC_API_RATE_LIMIT_PER_MINUTE = env.int(
        "PUBLIC_API_RATE_LIMIT_PER_MINUTE", 600, validate=lambda value: value > 0
    )
    PUBLIC_API_RATE_LIMIT_BURST = env.int(
        "PUBLIC_API_RATE_LIMIT_BURST", 50, validate=lambda value: value > 0
    )
    PUBLIC_API_TENANT_RATE_LIMIT_PER_MINUTE = env.int(
        "PUBLIC_API_TENANT_RATE_LIMIT_PER_MINUTE",
        1200,
        validate=lambda value: value > 0,
    )
    PUBLIC_API_TENANT_RATE_LIMIT_BURST = env.int(
        "PUBLIC_API_TENANT_RATE_LIMIT_BURST", 100, validate=lambda value: value > 0
    )

    #
    # Webhooks (S6.4, ADR-0009). WEBHOOKS_ENABLED=false enqueues nothing and
    # answers 503 WEBHOOKS_DISABLED on their routes (rollback switch);
    # WEBHOOK_DELIVERY_ENABLED=false only pauses the sending: the worker keeps
    # the pending deliveries. Each attempt has TIMEOUT_SECONDS in all; the
    # worker sends up to CONCURRENCY at once, one per endpoint, and groups
    # stock.changed every STOCK_BATCH_SECONDS. The history keeps
    # RETENTION_DAYS. WEBHOOK_ALLOW_PRIVATE_URLS lets an endpoint use http and
    # private addresses, for a receiver on this machine: local only
    #
    WEBHOOKS_ENABLED = env.bool("WEBHOOKS_ENABLED", True)
    WEBHOOK_DELIVERY_ENABLED = env.bool("WEBHOOK_DELIVERY_ENABLED", True)
    WEBHOOK_TIMEOUT_SECONDS = env.float(
        "WEBHOOK_TIMEOUT_SECONDS", 10.0, validate=lambda value: 1 <= value <= 30
    )
    WEBHOOK_CONCURRENCY = env.int(
        "WEBHOOK_CONCURRENCY", 8, validate=lambda value: 1 <= value <= 64
    )
    WEBHOOK_POLL_INTERVAL_SECONDS = env.float(
        "WEBHOOK_POLL_INTERVAL_SECONDS", 1.0, validate=lambda value: value > 0
    )
    WEBHOOK_STOCK_BATCH_SECONDS = env.float(
        "WEBHOOK_STOCK_BATCH_SECONDS", 30.0, validate=lambda value: value > 0
    )
    WEBHOOK_RETENTION_DAYS = env.int(
        "WEBHOOK_RETENTION_DAYS", 30, validate=lambda value: value > 0
    )
    WEBHOOK_ALLOW_PRIVATE_URLS = env.bool("WEBHOOK_ALLOW_PRIVATE_URLS", False)
    # The master key of the secrets kept in the database (the webhooks'):
    # Fernet keys separated by commas, the first one encrypts. Required outside
    # local, in the variable or in the file
    SECRET_ENCRYPTION_KEYS = env.str("SECRET_ENCRYPTION_KEYS", "")
    SECRET_ENCRYPTION_KEYS_FILE = env.str("SECRET_ENCRYPTION_KEYS_FILE", "")

    #
    # Refresh token cookie (HttpOnly, SameSite=Strict, Path=/api/auth)
    #
    AUTH_COOKIE_SECURE = env.bool("AUTH_COOKIE_SECURE", True)
    # Empty: the cookie belongs to the API host only
    AUTH_COOKIE_DOMAIN = env.str("AUTH_COOKIE_DOMAIN", "") or None

    #
    # Login lockout: MAX failures within the window lock the username (or the
    # client IP) for LOGIN_LOCKOUT_SECONDS
    #
    LOGIN_MAX_FAILURES_PER_USER = env.int("LOGIN_MAX_FAILURES_PER_USER", 5)
    LOGIN_MAX_FAILURES_PER_IP = env.int("LOGIN_MAX_FAILURES_PER_IP", 20)
    LOGIN_FAILURE_WINDOW_SECONDS = env.int("LOGIN_FAILURE_WINDOW_SECONDS", 900)
    LOGIN_LOCKOUT_SECONDS = env.int("LOGIN_LOCKOUT_SECONDS", 900)

    #
    # Largest request body accepted (413 above it)
    #
    MAX_REQUEST_BODY_BYTES = env.int("MAX_REQUEST_BODY_BYTES", 1_048_576)

    #
    # Bulk import (S5.8): the largest file and number of rows accepted; the
    # worker runs BATCH_SIZE rows per transaction for up to TICK_SECONDS each
    # POLL_INTERVAL (its health needs it back within a minute). The rows of an
    # import are deleted RETENTION_DAYS after it finished
    #
    IMPORT_MAX_FILE_BYTES = env.int("IMPORT_MAX_FILE_BYTES", 10 * 1_048_576)
    IMPORT_MAX_ROWS = env.int("IMPORT_MAX_ROWS", 50_000)
    IMPORT_BATCH_SIZE = env.int("IMPORT_BATCH_SIZE", 200)
    IMPORT_POLL_INTERVAL_SECONDS = env.float("IMPORT_POLL_INTERVAL_SECONDS", 2.0)
    IMPORT_TICK_SECONDS = env.float("IMPORT_TICK_SECONDS", 20.0)
    IMPORT_RETENTION_DAYS = env.int("IMPORT_RETENTION_DAYS", 30)

    #
    # Idempotency-Key (S3.1): the POS routes that create documents or move money
    # require it; false lets a request without it run as is (rollback switch).
    # The purge deletes the keys older than the retention
    #
    IDEMPOTENCY_KEY_REQUIRED = env.bool("IDEMPOTENCY_KEY_REQUIRED", True)
    IDEMPOTENCY_KEY_RETENTION_HOURS = env.int("IDEMPOTENCY_KEY_RETENTION_HOURS", 24)

    #
    # Docs config: /docs and the OpenAPI schemas, off unless enabled
    #
    DOCS_ENABLED = env.bool("DOCS_ENABLED", False)

    API_TITLE = "Faclab Core API"
    API_VERSION = "1.0.0"
    API_DESCRIPTION = """
**Faclab Core** is a comprehensive sales and inventory management platform.
It exposes two independent API surfaces — **Admin** for back-office operations
and **POS** for point-of-sale terminals — both sharing the same underlying
domain model.

> Use the **sidebar** on the left to navigate by module, or press
> <kbd>Ctrl</kbd>+<kbd>K</kbd> to search endpoints.

---

## API surfaces

| Surface | Base path | Docs | Purpose |
|---------|-----------|------|---------|
| **Admin** | `/api/admin` | [`/docs/admin`](/docs/admin) | Back-office: catalog, inventory, warehouses, customers, suppliers, purchasing, sales reporting, and analytics. |
| **POS** | `/api/pos` | [`/docs/pos`](/docs/pos) | Point-of-sale terminal: product lookup, customer search, shift management, full sales lifecycle, refunds, cash drawer, and operational reports. |

Authentication endpoints live under `/api/auth` and are included in **all three docs**, since both Admin and POS surfaces require a Bearer token.

---

## Authentication

All endpoints — except `POST /api/auth/login`, `POST /api/auth/select-tenant`, `POST /api/auth/refresh` and `POST /api/auth/logout` — require a **JWT Bearer token** (`EdDSA`, Ed25519) in the `Authorization` header:

```
Authorization: Bearer <accessToken>
```

### Flow

1. **Login** — `POST /api/auth/login` with `{ "username": "...", "password": "..." }`. Every token belongs to one tenant (company), the `tid` claim:
   - a user with **one** active tenant gets the `accessToken` and its `tenant` in the body, and the refresh token in the `faclab_refresh` cookie (`HttpOnly`, `SameSite=Strict`, `Path=/api/auth`);
   - a user with **several** gets a short-lived `selectionToken` and the list of `tenants`, and calls `POST /api/auth/select-tenant` with `{ "tenantId": "..." }` and `Authorization: Bearer <selectionToken>`, which answers like a one-tenant login.
2. **Authenticated calls** — send `Authorization: Bearer <accessToken>` on every request. **Switching tenants** is `POST /api/auth/select-tenant` with the current access token: it opens a session for the new tenant and closes the current one.
3. **Refresh** — when the access token expires (the API responds with a `TOKEN_EXPIRED` error), `POST /api/auth/refresh` with no body: the cookie identifies the session. Each refresh rotates the cookie; presenting an already used refresh token revokes the session (`TOKEN_REUSED`).
4. **Logout** — `POST /api/auth/logout` revokes the session and clears the cookie.
5. **Profile / change password** — `GET /api/auth/me` (the user, the active tenant and the tenants the user can switch to) and `POST /api/auth/change-password` operate on the currently authenticated user.

Browsers must send these three auth calls with credentials (`withCredentials` / `credentials: "include"`). By default, after 5 failed logins in 15 minutes the username is locked for 15 minutes (`LOGIN_LOCKED`, 429), even with the right password.

### Token lifetimes

| Token | Default TTL | Env override |
|-------|-------------|--------------|
| Access | 15 minutes | `JWT_ACCESS_TTL_SECONDS` |
| Refresh | 7 days | `JWT_REFRESH_TTL_SECONDS` |
| Tenant selection | 5 minutes | `JWT_SELECTION_TTL_SECONDS` |

Tokens are signed with Ed25519 (`EdDSA`); the public keys, by `kid`, are at `GET /.well-known/jwks.json`. The issuer claim is `JWT_ISSUER` (default `faclab-core`) and `aud` names `faclab-core` (access tokens also `faclab-invoicing`).

### Roles & permissions

Authorization is permission-based. A user holds one role in each tenant (its membership), and each role expands to a set of granular permissions (e.g. `product:read`, `sale:cancel`, `pos:operate`, `user:manage`). Endpoints declare the permissions they require; missing permissions return a `PERMISSION_DENIED` error.

| Role | Intended for | Highlights |
|------|--------------|------------|
| **ADMIN** | Company owner / IT | Full access to the tenant, including its user management. |
| **MANAGER** | Store / branch manager | Everything except user management and POS. Can confirm purchases, cancel sales, approve refunds. |
| **OPERATOR** | Back-office / warehouse staff | Inventory writes (movements, lots, serials, adjustments, transfers), product/customer/supplier writes, sale & purchase create — no critical approvals, no POS, no user management. |
| **VIEWER** | Auditors / accountants | Read-only across the catalog, inventory, sales, purchases, customers, suppliers, alerts and reports. |
| **CASHIER** | POS terminal operator | POS operations, sale create/read, customer create/read, product/stock read, POS reports. No inventory writes, no approvals, no admin. |

### Authorization errors

| HTTP | Error code | Meaning |
|------|------------|---------|
| 401 | `INVALID_CREDENTIALS` | Wrong username/password, or user is inactive. |
| 401 | `TOKEN_EXPIRED` | Access (or refresh) token expired — call `/api/auth/refresh` or log in again. |
| 401 | `INVALID_TOKEN` | Token is malformed or signed with a wrong secret, or its session ended — log in again. |
| 401 | `TOKEN_REUSED` | An already used refresh token was presented; the session was revoked — log in again. |
| 401 | `TENANT_REQUIRED` | The access token has no tenant (issued before tenants existed) — log in again. |
| 403 | `PERMISSION_DENIED` | No token, or authenticated but missing one or more permissions required by the endpoint. |
| 403 | `PASSWORD_CHANGE_REQUIRED` | The user must change their password first. |
| 403 | `NO_ACTIVE_TENANT` | Right credentials, but the user has no active membership in an active tenant. |
| 403 | `TENANT_ACCESS_DENIED` | `select-tenant` with a tenant the user can't enter. |
| 429 | `LOGIN_LOCKED` | Too many failed logins for this username or client; wait and try again. |

### Trying it from this UI

Click the **lock icon** at the top of any endpoint, choose **`bearerAuth`**, and paste the `accessToken` value (without the `Bearer ` prefix). Scalar will inject the `Authorization` header on every "Try it" request.

### curl example

```bash
# 1. Login (the refresh cookie is kept in cookies.txt)
TOKENS=$(curl -s -c cookies.txt -X POST http://localhost:3000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"change-me"}')

ACCESS=$(echo "$TOKENS" | jq -r '.data.accessToken')

# 2. Call a protected endpoint
curl -s http://localhost:3000/api/auth/me \
  -H "Authorization: Bearer $ACCESS"

# 3. Refresh when the access token expires (sends and rotates the cookie)
curl -s -b cookies.txt -c cookies.txt -X POST http://localhost:3000/api/auth/refresh
```

---

## Response format

All successful responses are wrapped in a standard envelope:

```json
{
  "data": { ... },
  "meta": {
    "requestId": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2025-01-15T10:30:00Z"
  }
}
```

Paginated lists include additional pagination metadata:

```json
{
  "data": [ ... ],
  "meta": {
    "requestId": "...",
    "timestamp": "...",
    "pagination": { "total": 142, "limit": 100, "offset": 0 }
  }
}
```

---

## Error format

All errors follow a consistent structure with one or more error entries:

```json
{
  "errors": [
    {
      "code": "NOT_FOUND",
      "message": "Product with id 99 not found",
      "field": null
    }
  ],
  "meta": {
    "requestId": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2025-01-15T10:30:00Z"
  }
}
```

### HTTP status codes

| Status | Meaning | Typical cause |
|--------|---------|---------------|
| **400** | Business rule violation | Domain or application error (e.g. confirming an already-confirmed sale) |
| **404** | Not found | The requested resource does not exist |
| **409** | Integrity conflict | Cannot delete/modify because the resource is referenced elsewhere |
| **422** | Validation error | Request body or query parameters failed validation |
| **500** | Internal error | Unexpected server-side failure |

---

## Conventions

- **Field naming**: All JSON fields use **camelCase** (e.g. `customerId`, `unitPrice`).
- **Pagination**: List endpoints accept `limit` (1-1000, default 100) and `offset` (default 0) query parameters.
- **IDs**: All resource IDs are positive integers.
- **Decimals**: Monetary and percentage values are returned as floating-point numbers.
- **Timestamps**: All timestamps are in ISO 8601 format with UTC timezone.
"""

    API_OPENAPI_TAGS: list[dict] = [
        # Administration — Auth & Users
        {
            "name": "Auth",
            "description": (
                "Authentication endpoints — login, refresh access tokens, get the "
                "current authenticated user, and change password. "
                "**`POST /api/auth/login` and `POST /api/auth/refresh` are public**; "
                "all other endpoints require a Bearer token."
            ),
        },
        {
            "name": "Users",
            "description": (
                "Administer system users: create, list, view, update role, "
                "activate and deactivate, and limit them to some branches. "
                "Requires the `user:manage` permission."
            ),
        },
        {
            "name": "Imports",
            "description": (
                "Bulk import of initial data from CSV or XLSX: products, "
                "presentations, price list prices, customers, suppliers and opening "
                "stock. A file is validated row by row without writing anything; "
                "once confirmed, the worker imports it in batches. Requires the "
                "`import:write` permission (admins)."
            ),
        },
        {
            "name": "Integrations",
            "description": (
                "Integration clients of the tenant (S6.2): external systems that "
                "call the API with OAuth 2.0 client credentials. Each has scopes, "
                "optional branches and source networks, and up to two active "
                "secrets (rotation); a secret is shown only when it is created. "
                "Requires the `integration:manage` permission (admins)."
            ),
        },
        {
            "name": "Webhooks",
            "description": (
                "Webhook endpoints of the tenant (S6.4): HTTPS URLs that receive "
                "the events they subscribe to (sales, invoices, credit notes, "
                "stock, products), signed with the Standard Webhooks scheme. "
                "Retries for about three days; an endpoint that keeps failing is "
                "disabled. History of 30 days, test event and manual resend. "
                "Requires the `integration:manage` permission (admins)."
            ),
        },
        {
            "name": "OAuth",
            "description": (
                "`POST /api/oauth/token`: the access token of an integration "
                "client (client credentials, RFC 6749 §4.4). Public: the client "
                "authenticates with its client_id and secret. Answers follow RFC "
                "6749, not the API envelope."
            ),
        },
        {
            "name": "Audit Log",
            "description": (
                "Sensitive operations of the tenant (prices, stock, cancellations, "
                "refunds, cash, shifts, users, organization): who did them, on what, "
                "and the relevant fields before and after. Entries are never changed "
                "or deleted. Requires the `audit:read` permission (admins)."
            ),
        },
        # Admin — Organization
        {
            "name": "Branches",
            "description": (
                "The tenant's branches: SRI establishments with a three-digit code "
                "(001-999), unique in the tenant. The main branch (matriz) is "
                "created at provisioning. Requires `organization:read` / "
                "`organization:write`."
            ),
        },
        {
            "name": "Emission Points",
            "description": (
                "SRI emission points of a branch, with a three-digit code unique "
                "in the branch."
            ),
        },
        {
            "name": "POS Terminals",
            "description": (
                "POS terminals of a branch: each issues by an emission point and "
                "takes stock from a location of a warehouse of the same branch."
            ),
        },
        # Admin — Catalog
        {
            "name": "Categories",
            "description": "Organize the product catalog with a structured category system.",
        },
        {
            "name": "Units of Measure",
            "description": "Manage units of measure used across products (e.g., kg, liters, units, boxes).",
        },
        {
            "name": "Products",
            "description": (
                "Full product catalog management: SKU, pricing, categorization, "
                "stock thresholds, and service flags."
            ),
        },
        # Admin — Inventory
        {
            "name": "Warehouses",
            "description": "Manage physical warehouse facilities where inventory is stored.",
        },
        {
            "name": "Locations",
            "description": "Manage specific storage locations within warehouses — shelves, bins, and zones.",
        },
        {
            "name": "Stock",
            "description": "Query real-time stock levels per product and storage location.",
        },
        {
            "name": "Movements",
            "description": (
                "Record and query inventory movements (IN/OUT). Includes manual entries "
                "and system-generated movements from confirmed or cancelled sales."
            ),
        },
        # Admin — Customers
        {
            "name": "Customers",
            "description": (
                "Manage customer profiles: tax ID (RUC), credit limits, payment terms, "
                "and activation status."
            ),
        },
        {
            "name": "Customer Contacts",
            "description": "Manage individual contacts associated with a customer.",
        },
        # Admin — Suppliers
        {
            "name": "Suppliers",
            "description": (
                "Manage supplier profiles: tax ID, payment terms, lead times, "
                "and activation status."
            ),
        },
        {
            "name": "Supplier Contacts",
            "description": "Manage individual contacts associated with a supplier.",
        },
        {
            "name": "Supplier Products",
            "description": (
                "Manage the purchase catalog: link products to suppliers with "
                "purchase price, supplier SKU, and minimum order quantity."
            ),
        },
        # Admin — Lots & Serials
        {
            "name": "Lots",
            "description": "Lot management — expiry tracking, lot quantities, and perishable product control.",
        },
        {
            "name": "Serials",
            "description": "Serial number tracking — unit-level traceability for electronics and equipment.",
        },
        # Admin — Purchasing
        {
            "name": "Purchase Orders",
            "description": "Manage purchase orders: create, send to supplier, receive goods, and cancel.",
        },
        {
            "name": "Purchase Order Items",
            "description": "Manage line items within a purchase order.",
        },
        # Admin — Adjustments
        {
            "name": "Adjustments",
            "description": "Manage inventory adjustments — physical counts, corrections, write-offs, and expiration entries.",
        },
        {
            "name": "Adjustment Items",
            "description": "Manage individual line items within an inventory adjustment.",
        },
        # Admin — Transfers
        {
            "name": "Transfers",
            "description": "Manage stock transfers between warehouse locations.",
        },
        {
            "name": "Transfer Items",
            "description": "Manage individual line items within a stock transfer.",
        },
        # Admin — Alerts
        {
            "name": "Alerts",
            "description": "Stock level alerts: low stock, out of stock, reorder points, and expiring lots.",
        },
        # Admin — Sales
        {
            "name": "Sales",
            "description": "Read-only access to all sales data for back-office reporting and auditing.",
        },
        {
            "name": "Invoice Discrepancies",
            "description": (
                "Sales that don't square with faclab-invoicing: confirmed without an "
                "invoice result after the threshold, or with an invoice the SRI "
                "authorized after the sale was cancelled. The worker's reconciliation "
                "opens and resolves them; users resend the sale or mark them reviewed."
            ),
        },
        # Admin — Reports
        {
            "name": "Dashboard",
            "description": (
                "Home page summary: inventory value, warehouse summary and "
                "alert counts in one call."
            ),
        },
        {
            "name": "Inventory Reports",
            "description": (
                "Inventory analytics: valuation, product rotation, "
                "movement history, and warehouse stock summaries."
            ),
        },
        # POS
        {
            "name": "Product Search",
            "description": "Product lookup for point-of-sale operations.",
        },
        {
            "name": "Customer Search",
            "description": "Customer lookup for point-of-sale, including search by tax ID (RUC).",
        },
        {
            "name": "Terminals",
            "description": (
                "The active terminals of the branch in `X-Branch-Id`, to choose "
                "the one the POS runs on."
            ),
        },
        {
            "name": "Shifts",
            "description": (
                "Shift management: open and close cashier shifts, "
                "track opening/closing balances, and calculate discrepancies."
            ),
        },
        {
            "name": "POS Sales",
            "description": (
                "Full sales lifecycle for the point-of-sale terminal: "
                "create, add items, confirm, cancel, and register payments."
            ),
        },
        {
            "name": "Refunds",
            "description": (
                "Process refunds for confirmed sales: create partial/total refunds, "
                "process payments, and automatically restock inventory."
            ),
        },
        {
            "name": "Cash Drawer",
            "description": (
                "Cash drawer movements: register cash-in/cash-out operations "
                "within an open shift and query cash summaries."
            ),
        },
        {
            "name": "POS Reports",
            "description": (
                "POS operational reports: X-Report (mid-shift), Z-Report (closing), "
                "daily sales summary, and sales breakdown by payment method."
            ),
        },
    ]

    API_TAG_GROUPS: list[dict] = [
        {
            "name": "Administration",
            "tags": [
                "Auth",
                "OAuth",
                "Users",
                "Integrations",
                "Webhooks",
                "Audit Log",
                "Imports",
            ],
        },
        {
            "name": "Organization",
            "tags": ["Branches", "Emission Points", "POS Terminals"],
        },
        {
            "name": "Catalog",
            "tags": [
                "Categories",
                "Units of Measure",
                "Products",
            ],
        },
        {
            "name": "Inventory",
            "tags": [
                "Warehouses",
                "Locations",
                "Stock",
                "Movements",
            ],
        },
        {
            "name": "Lots & Serials",
            "tags": ["Lots", "Serials"],
        },
        {
            "name": "Customers",
            "tags": ["Customers", "Customer Contacts"],
        },
        {
            "name": "Suppliers",
            "tags": [
                "Suppliers",
                "Supplier Contacts",
                "Supplier Products",
            ],
        },
        {
            "name": "Purchasing",
            "tags": ["Purchase Orders", "Purchase Order Items"],
        },
        {
            "name": "Adjustments",
            "tags": ["Adjustments", "Adjustment Items"],
        },
        {
            "name": "Transfers",
            "tags": ["Transfers", "Transfer Items"],
        },
        {
            "name": "Alerts",
            "tags": ["Alerts"],
        },
        {
            "name": "Sales",
            "tags": ["Sales", "Invoice Discrepancies"],
        },
        {
            "name": "Reports",
            "tags": ["Dashboard", "Inventory Reports"],
        },
        {
            "name": "POS",
            "tags": [
                "Terminals",
                "Product Search",
                "Customer Search",
                "Shifts",
                "POS Sales",
                "Refunds",
                "Cash Drawer",
                "POS Reports",
            ],
        },
    ]

    def __init__(self):
        # Without its own URL the worker shares the API's (local SQLite, or a
        # single role); set here so it sees the subclass's DB_CONNECTION_STRING
        self.DB_WORKER_CONNECTION_STRING = (
            self.DB_WORKER_URL or self.DB_CONNECTION_STRING
        )

    def get_otel_config(self) -> OpenTelemetryConfig:
        return OpenTelemetryConfig(
            service_name=self.OTEL_SERVICE_NAME,
            service_version=self.SERVICE_VERSION,
            otlp_endpoint=self.OTEL_OTLP_ENDPOINT,
            environment=self.OTEL_ENVIRONMENT,
            enabled=self.OTEL_ENABLED,
            sampling_rate=self.OTEL_SAMPLING_RATE,
            insecure=self.OTEL_EXPORTER_OTLP_INSECURE,
        )

    def get_docs_config(self) -> DocsConfig:
        return DocsConfig(
            title=self.API_TITLE,
            version=self.API_VERSION,
            description=self.API_DESCRIPTION,
            openapi_tags=self.API_OPENAPI_TAGS,
            tag_groups=self.API_TAG_GROUPS,
            enabled=self.DOCS_ENABLED,
        )
