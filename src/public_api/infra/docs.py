"""The public documentation of the API (S6.5): one Scalar page with the guides
for integrators, the reference of every `/api/v1` route and the webhook events.

The page's document is built from the contracts, never instead of them:

- core's public OpenAPI (`public_openapi`, the snapshot the CI compares);
- the pinned copy of faclab-invoicing's (`docs/public-api/invoicing/`,
  `make public-openapi-invoicing` refreshes it), the `/api/v1/invoices` routes
  it serves behind the same domain and token;
- each webhook event's JSON Schema as an OpenAPI 3.1 `webhooks` entry;
- the Markdown guides of `docs/public-api/` as its introduction.

Links between guides become bold text (they are all on the same page); links
to the examples and schemas point at `FILES_PATH`, where those files are
served as they are.
"""

import copy
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from src.public_api.infra.openapi import public_openapi
from src.webhooks.infra.contracts import event_schema
from src.webhooks.infra.schemas import EVENT_MODELS

PUBLIC_DOCS = Path(__file__).resolve().parents[3] / "docs/public-api"
INVOICING_SPEC = PUBLIC_DOCS / "invoicing/openapi-v1.json"
# Where the page links the examples and the JSON Schemas
FILES_PATH = "/docs/public/files"
ENDPOINTS_TAG = "Webhook endpoints"

# The guides in the order of the page; their first heading is their title
GUIDES = (
    "primeros-pasos.md",
    "autenticacion.md",
    "sincronizar-catalogo-y-stock.md",
    "ventas-desde-ecommerce.md",
    "facturas-por-webhook.md",
    "webhooks.md",
    "errores.md",
    "limites.md",
    "CHANGELOG.md",
)

# A relative Markdown link: `[text](target)`, not `http…`, `#…` nor `/…`
_RELATIVE_LINK = re.compile(r"\[([^\]]+)\]\((?!https?://|#|/|mailto:)([^)\s]+)\)")


class DocsMergeError(ValueError):
    """The invoicing document can't be added to core's as it is"""


def _relink(markdown: str) -> str:
    def replace(match: re.Match) -> str:
        text, target = match.groups()
        path = target.split("#", 1)[0]
        if path in GUIDES or path.endswith(".md"):
            return f"**{text}**"
        return f"[{text}]({FILES_PATH}/{target})"

    return _RELATIVE_LINK.sub(replace, markdown)


def guides_markdown() -> str:
    """Every guide, one after the other, with their links fixed"""
    return "\n\n".join(
        _relink((PUBLIC_DOCS / name).read_text(encoding="utf-8").strip())
        for name in GUIDES
    )


def _merge_invoicing(document: dict, invoicing: dict) -> None:
    shared = set(document["paths"]) & set(invoicing.get("paths", {}))
    if shared:
        raise DocsMergeError(f"paths in both documents: {sorted(shared)}")
    schemas = document.setdefault("components", {}).setdefault("schemas", {})
    their_schemas = invoicing.get("components", {}).get("schemas", {})
    if set(schemas) & set(their_schemas):
        raise DocsMergeError(
            f"schemas in both documents: {sorted(set(schemas) & set(their_schemas))}"
        )
    # Invoicing's routes use core's token: its scopes must be core's
    ours = document["components"]["securitySchemes"]
    for name, scheme in (
        invoicing.get("components", {}).get("securitySchemes", {}).items()
    ):
        if name not in ours:
            raise DocsMergeError(f"security scheme {name} is not core's")
        their_scopes = scheme["flows"]["clientCredentials"]["scopes"]
        our_scopes = ours[name]["flows"]["clientCredentials"]["scopes"]
        if set(their_scopes) - set(our_scopes):
            raise DocsMergeError(
                f"scopes core doesn't have: {sorted(set(their_scopes) - set(our_scopes))}"
            )
    document["paths"].update(invoicing["paths"])
    schemas.update(their_schemas)
    known = {tag["name"] for tag in document.get("tags", [])}
    document.setdefault("tags", []).extend(
        tag for tag in invoicing.get("tags", []) if tag["name"] not in known
    )


def _schema_name(event_type: str) -> str:
    """`sale.confirmed` → `WebhookSaleConfirmed`"""
    return "Webhook" + "".join(
        part.capitalize() for part in re.split(r"[._]", event_type)
    )


def _hoisted(value: Any, prefix: str) -> Any:
    """The event's own `$defs` move to `components/schemas`, under its prefix"""
    if isinstance(value, dict):
        return {
            key: (
                item.replace("#/$defs/", f"#/components/schemas/{prefix}")
                if key == "$ref" and isinstance(item, str)
                else _hoisted(item, prefix)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_hoisted(item, prefix) for item in value]
    return value


def _add_webhooks(document: dict) -> None:
    schemas = document.setdefault("components", {}).setdefault("schemas", {})
    webhooks = document.setdefault("webhooks", {})
    for event_type in EVENT_MODELS:
        name = _schema_name(event_type)
        schema = _hoisted(event_schema(event_type), name)
        hoisted = {
            f"{name}{key}": definition
            for key, definition in schema.pop("$defs", {}).items()
        }
        schema.pop("$schema", None)
        schema.pop("$id", None)
        hoisted[name] = schema
        if set(hoisted) & set(schemas):
            raise DocsMergeError(
                f"schemas in both documents: {sorted(set(hoisted) & set(schemas))}"
            )
        schemas.update(hoisted)
        webhooks[event_type] = {
            "post": {
                "summary": event_type,
                "description": (
                    "Faclab sends it as a signed `POST` (headers `webhook-id`, "
                    "`webhook-timestamp` and `webhook-signature`). Answer 2xx "
                    "within 10 s; anything else is retried."
                ),
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{name}"}
                        }
                    },
                },
                "responses": {"200": {"description": "Received"}},
            }
        }


def _rename_tag(document: dict, old: str, new: str) -> None:
    for tag in document.get("tags", []):
        if tag["name"] == old:
            tag["name"] = new
    for path_item in document["paths"].values():
        for operation in path_item.values():
            if isinstance(operation, dict) and "tags" in operation:
                operation["tags"] = [new if t == old else t for t in operation["tags"]]


def build_docs_document(core: dict, invoicing: dict | None) -> dict:
    document = copy.deepcopy(core)
    if invoicing is not None:
        _merge_invoicing(document, copy.deepcopy(invoicing))
    # The page also lists the events under "Webhooks": the routes that manage
    # the endpoints get a name of their own (only here, not in the contract)
    _rename_tag(document, "Webhooks", ENDPOINTS_TAG)
    _add_webhooks(document)
    document["info"] = {
        **document["info"],
        "title": "Faclab API",
        "description": guides_markdown(),
    }
    return document


@cache
def _invoicing() -> dict | None:
    """The pinned copy; without it the page only has core's routes"""
    if not INVOICING_SPEC.exists():
        return None
    return json.loads(INVOICING_SPEC.read_text(encoding="utf-8"))


def public_docs_document(app: FastAPI) -> dict:
    """What `/docs/public` shows, built once per process"""
    cached = getattr(app.state, "public_docs_document", None)
    if cached is None:
        cached = build_docs_document(public_openapi(app), _invoicing())
        app.state.public_docs_document = cached
    return cached
