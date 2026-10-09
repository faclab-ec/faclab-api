from dataclasses import dataclass

from environs import Env

env = Env()


@dataclass
class OpenTelemetryConfig:
    service_name: str
    otlp_endpoint: str
    environment: str
    enabled: bool = True
    sampling_rate: float = 1.0


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
    ENVIRONMENT = env("ENVIRONMENT", "local")

    #
    # Logging config
    #
    LOG_LEVEL = env("LOG_LEVEL", "INFO")

    #
    # Database config
    #
    DB_CONNECTION_STRING = env("DATABASE_URL", "sqlite:///./warehouse.db")

    #
    # OpenTelemetry config
    #
    OTEL_OTLP_ENDPOINT = env("OTEL_OTLP_ENDPOINT", "http://localhost:4317")
    OTEL_SERVICE_NAME = env("OTEL_SERVICE_NAME", SERVICE_NAME)
    OTEL_ENVIRONMENT = env("OTEL_ENVIRONMENT", ENVIRONMENT)
    OTEL_ENABLED = env.bool("OTEL_ENABLED", True)
    OTEL_SAMPLING_RATE = env.float("OTEL_SAMPLING_RATE", 1.0)

    #
    # Kafka config
    #
    KAFKA_BOOTSTRAP_SERVERS = env("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    KAFKA_ENABLED = env.bool("KAFKA_ENABLED", False)
    # How often the outbox relay looks for unpublished messages; it also wakes
    # up right after a commit that wrote one
    OUTBOX_POLL_INTERVAL_SECONDS = env.float("OUTBOX_POLL_INTERVAL_SECONDS", 5.0)
    # Consumer group for the topics core reads (invoice results); every replica
    # shares it so each message is handled once
    KAFKA_CONSUMER_GROUP_ID = env("KAFKA_CONSUMER_GROUP_ID", "faclab-core")

    #
    # Auth / JWT config
    #
    JWT_SECRET = env("JWT_SECRET", "dev-only-change-me")
    JWT_ACCESS_TTL_SECONDS = env.int("JWT_ACCESS_TTL_SECONDS", 900)
    JWT_REFRESH_TTL_SECONDS = env.int("JWT_REFRESH_TTL_SECONDS", 604800)
    JWT_ISSUER = env("JWT_ISSUER", "faclab-core")

    #
    # Docs config
    #
    DOCS_ENABLED = env.bool("DOCS_ENABLED", True)

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

All endpoints — except `POST /api/auth/login` and `POST /api/auth/refresh` — require a **JWT Bearer token** (`HS256`) in the `Authorization` header:

```
Authorization: Bearer <accessToken>
```

### Flow

1. **Login** — `POST /api/auth/login` with `{ "username": "...", "password": "..." }`. Receive an `accessToken` and a `refreshToken`.
2. **Authenticated calls** — send `Authorization: Bearer <accessToken>` on every request.
3. **Refresh** — when the access token expires (the API responds with a `TOKEN_EXPIRED` error), `POST /api/auth/refresh` with `{ "refreshToken": "..." }` to obtain a new pair. The refresh token is also rotated.
4. **Profile / change password** — `GET /api/auth/me` and `POST /api/auth/change-password` operate on the currently authenticated user.

### Token lifetimes

| Token | Default TTL | Env override |
|-------|-------------|--------------|
| Access | 15 minutes | `JWT_ACCESS_TTL_SECONDS` |
| Refresh | 7 days | `JWT_REFRESH_TTL_SECONDS` |

The signing secret is `JWT_SECRET` and the issuer claim is `JWT_ISSUER` (default `faclab-core`).

### Roles & permissions

Authorization is permission-based. Each user holds a single role, and each role expands to a set of granular permissions (e.g. `product:read`, `sale:cancel`, `pos:operate`, `user:manage`). Endpoints declare the permissions they require; missing permissions return a `PERMISSION_DENIED` error.

| Role | Intended for | Highlights |
|------|--------------|------------|
| **ADMIN** | System owner / IT | Full access, including user management. |
| **MANAGER** | Store / branch manager | Everything except user management and POS. Can confirm purchases, cancel sales, approve refunds. |
| **OPERATOR** | Back-office / warehouse staff | Inventory writes (movements, lots, serials, adjustments, transfers), product/customer/supplier writes, sale & purchase create — no critical approvals, no POS, no user management. |
| **VIEWER** | Auditors / accountants | Read-only across the catalog, inventory, sales, purchases, customers, suppliers, alerts and reports. |
| **CASHIER** | POS terminal operator | POS operations, sale create/read, customer create/read, product/stock read, POS reports. No inventory writes, no approvals, no admin. |

### Authorization errors

| HTTP | Error code | Meaning |
|------|------------|---------|
| 400 | `INVALID_CREDENTIALS` | Wrong username/password, or user is inactive. |
| 400 | `TOKEN_EXPIRED` | Access (or refresh) token expired — call `/api/auth/refresh` or log in again. |
| 400 | `INVALID_TOKEN` | Token is malformed, signed with a wrong secret, or refers to a user that no longer exists/is active. |
| 400 | `PERMISSION_DENIED` | Authenticated, but missing one or more permissions required by the endpoint. |

### Trying it from this UI

Click the **lock icon** at the top of any endpoint, choose **`bearerAuth`**, and paste the `accessToken` value (without the `Bearer ` prefix). Scalar will inject the `Authorization` header on every "Try it" request.

### curl example

```bash
# 1. Login
TOKENS=$(curl -s -X POST http://localhost:3000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"change-me"}')

ACCESS=$(echo "$TOKENS" | jq -r '.data.accessToken')
REFRESH=$(echo "$TOKENS" | jq -r '.data.refreshToken')

# 2. Call a protected endpoint
curl -s http://localhost:3000/api/auth/me \
  -H "Authorization: Bearer $ACCESS"

# 3. Refresh when the access token expires
curl -s -X POST http://localhost:3000/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d "{\"refreshToken\":\"$REFRESH\"}"
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
                "activate and deactivate. Requires the `user:manage` permission."
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
        # Admin — Reports
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
            "tags": ["Auth", "Users"],
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
            "tags": ["Sales"],
        },
        {
            "name": "Reports",
            "tags": ["Inventory Reports"],
        },
        {
            "name": "POS",
            "tags": [
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

    def get_otel_config(self) -> OpenTelemetryConfig:
        return OpenTelemetryConfig(
            service_name=self.OTEL_SERVICE_NAME,
            otlp_endpoint=self.OTEL_OTLP_ENDPOINT,
            environment=self.OTEL_ENVIRONMENT,
            enabled=self.OTEL_ENABLED,
            sampling_rate=self.OTEL_SAMPLING_RATE,
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
