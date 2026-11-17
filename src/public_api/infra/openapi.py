"""The OpenAPI document of the public API (S6.3): only `/api/v1` and the token
endpoint, with its own tags and the OAuth 2.0 client credentials scheme.

It is the published contract: `docs/public-api/openapi-v1.json` keeps the
current version (`make public-openapi` writes it, a test fails while it
differs) and the CI compares it with the base branch's to refuse an
incompatible change.
"""

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from src.auth.domain.scopes import Scope
from src.public_api.infra.dependencies import OAUTH_SCHEME
from src.public_api.infra.rate_limit import PUBLIC_API_PREFIX

VERSION = "1.0.0"
TOKEN_PATH = "/api/oauth/token"
# The tag of each public router in the app's own document: `v1 Products`
TAG_PREFIX = "v1 "
SNAPSHOT = Path(__file__).resolve().parents[3] / "docs/public-api/openapi-v1.json"

DESCRIPTION = """
The public API of Faclab for integrations: a contract of its own, versioned in
the URL, that doesn't change with the application's frontend.

- **Authentication:** OAuth 2.0 client credentials at `POST /api/oauth/token`
  with the client's id and secret; the access token lasts 15 minutes. Each
  route requires a scope.
- **Tenant and branch:** the company comes from the token. A client may be
  limited to some branches; `X-Branch-Id` names the branch of an operation.
- **Format:** JSON in camelCase. Money and quantities are decimal strings
  (`"12.50"`), never floating point numbers; timestamps are ISO 8601 in UTC.
- **Lists:** `limit` (up to 200) and `offset`, always in a stable order (the id
  breaks ties), `sort` among the fields of each resource, and `updatedSince`
  to sync.
- **Retries:** every POST requires `Idempotency-Key` (a UUID per operation):
  repeating it returns the same response, with `Idempotent-Replayed: true`.
- **Limits:** per client and per company; over them, 429 `RATE_LIMITED` with
  `Retry-After`. Every response carries `RateLimit-Limit`,
  `RateLimit-Remaining`, `RateLimit-Reset` and `RateLimit-Policy`.
- **Errors:** `{"errors": [{"code", "message", "field"?}], "meta"}` with codes
  of a stable catalog. Clients must ignore fields they don't know: new ones
  are added without a new version.
""".strip()

TAGS = [
    {"name": "OAuth", "description": "Access tokens of the integration clients."},
    {
        "name": "Branches",
        "description": "Where the client operates: emission points and locations.",
    },
    {"name": "Products", "description": "Catalog: products and presentations."},
    {"name": "Price Lists", "description": "Price lists and their prices."},
    {"name": "Stock", "description": "Stock by branch, warehouse and location."},
    {"name": "Customers", "description": "Customers by identification."},
    {"name": "Sales", "description": "Sales of every channel; sales of the API."},
]

# The headers the shared dependencies declare, as the public API requires them
HEADERS = {
    ("header", "X-Branch-Id"): {
        "required": True,
        "description": (
            "The branch of the operation: one the client may operate in "
            "(`BRANCH_ACCESS_DENIED`, 403; `BRANCH_REQUIRED` without it)"
        ),
        "schema": {"type": "string", "pattern": "^[1-9][0-9]*$", "examples": ["12"]},
    },
    ("header", "Idempotency-Key"): {
        "required": True,
        "description": (
            "A UUID generated once per operation and resent on every retry of "
            "it: the operation runs once and a retry gets its response "
            "(`IDEMPOTENCY_KEY_REQUIRED` without it, `IDEMPOTENCY_KEY_REUSED` "
            "with another body)"
        ),
        "schema": {"type": "string", "format": "uuid"},
    },
}

SCOPE_DESCRIPTIONS = {
    Scope.PRODUCTS_READ: "Read products, categories, units and presentations",
    Scope.PRODUCTS_WRITE: "Create and update products",
    Scope.PRICES_READ: "Read price lists",
    Scope.PRICES_WRITE: "Change price lists",
    Scope.STOCK_READ: "Read stock by branch and warehouse",
    Scope.INVENTORY_WRITE: "Inventory documents (adjustments, transfers)",
    Scope.CUSTOMERS_READ: "Read customers",
    Scope.CUSTOMERS_WRITE: "Create and update customers",
    Scope.SALES_READ: "Read sales",
    Scope.SALES_WRITE: "Create and cancel sales",
    Scope.INVOICES_READ: "Read invoices and credit notes, their XML and RIDE",
    Scope.WEBHOOKS_MANAGE: "Webhook subscriptions",
}


def public_route(route: object) -> bool:
    return isinstance(route, APIRoute) and (
        route.path.startswith(PUBLIC_API_PREFIX) or route.path == TOKEN_PATH
    )


def public_openapi(app: FastAPI) -> dict:
    schema = get_openapi(
        title="Faclab API",
        version=VERSION,
        description=DESCRIPTION,
        routes=[route for route in app.routes if public_route(route)],
        tags=TAGS,
    )
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            operation["tags"] = [
                tag.removeprefix(TAG_PREFIX) for tag in operation.get("tags", [])
            ]
            for parameter in operation.get("parameters", []):
                header = HEADERS.get((parameter["in"], parameter["name"]))
                if header is not None:
                    parameter.update(header)
    schema.setdefault("components", {})["securitySchemes"] = {
        OAUTH_SCHEME: security_scheme()
    }
    return schema


def security_scheme() -> dict:
    return {
        "type": "oauth2",
        "description": (
            "OAuth 2.0 client credentials: the client's id and secret with HTTP "
            "Basic (or in the form) at the token endpoint"
        ),
        "flows": {
            "clientCredentials": {
                "tokenUrl": TOKEN_PATH,
                "scopes": {scope.value: SCOPE_DESCRIPTIONS[scope] for scope in Scope},
            }
        },
    }


def render(schema: dict) -> str:
    """How the snapshot is written: stable and readable in a diff"""
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    """`make public-openapi`: writes the snapshot from the app's routes"""
    from main import app

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(render(public_openapi(app)))
    print(f"wrote {SNAPSHOT.relative_to(SNAPSHOT.parents[2])}")


if __name__ == "__main__":
    main()
