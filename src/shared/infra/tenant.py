from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import structlog
from opentelemetry import trace
from wireup import injectable

from src.shared.domain.tenant import TenantContext, require_tenant, use_tenant

TENANT_ID_ATTRIBUTE = "faclab.tenant.id"
BRANCH_ID_ATTRIBUTE = "faclab.branch.id"
# Kafka header with the tenant of a message (the outbox writes it, consumers read it)
TENANT_HEADER = "faclab-tenant-id"


@contextmanager
def tenant_scope(context: TenantContext) -> Generator[TenantContext, None, None]:
    """Corre el bloque en esa empresa: la ven los repositorios, la sesión de
    base (`SET LOCAL app.tenant_id`), los eventos, los logs (`faclab.tenant.id`)
    y el span activo. Si el contexto trae sucursal, también va a los logs y al
    span (`faclab.branch.id`)."""
    attributes: dict[str, Any] = {TENANT_ID_ATTRIBUTE: str(context.tenant_id)}
    if context.branch_id is not None:
        attributes[BRANCH_ID_ATTRIBUTE] = context.branch_id
    trace.get_current_span().set_attributes(attributes)
    with (
        use_tenant(context),
        structlog.contextvars.bound_contextvars(**attributes),
    ):
        yield context


def tenant_criteria(*models: Any) -> list[Any]:
    """The conditions that keep a query in the context's tenant, one per
    tenant-scoped model it reads. The base repository adds them by itself;
    queries written by hand (read models, reports, custom repository methods)
    add them explicitly. Without a context it raises."""
    names = ", ".join(model.__name__ for model in models)
    tenant_id = require_tenant(f"reading {names}").tenant_id
    return [model.tenant_id == tenant_id for model in models]


@injectable(lifetime="scoped")
def tenant_context() -> TenantContext:
    """La empresa del scope, para el código que la recibe por inyección. Falla
    solo si alguien la pide sin contexto."""
    return require_tenant()
