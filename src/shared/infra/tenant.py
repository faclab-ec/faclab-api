from collections.abc import Generator
from contextlib import contextmanager

import structlog
from opentelemetry import trace
from wireup import injectable

from src.shared.domain.tenant import TenantContext, require_tenant, use_tenant

TENANT_ID_ATTRIBUTE = "faclab.tenant.id"
# Kafka header with the tenant of a message (the outbox writes it, consumers read it)
TENANT_HEADER = "faclab-tenant-id"


@contextmanager
def tenant_scope(context: TenantContext) -> Generator[TenantContext, None, None]:
    """Corre el bloque en esa empresa: la ven los repositorios, la sesión de
    base (`SET LOCAL app.tenant_id`), los eventos, los logs (`faclab.tenant.id`)
    y el span activo."""
    tenant_id = str(context.tenant_id)
    trace.get_current_span().set_attribute(TENANT_ID_ATTRIBUTE, tenant_id)
    with (
        use_tenant(context),
        structlog.contextvars.bound_contextvars(**{TENANT_ID_ATTRIBUTE: tenant_id}),
    ):
        yield context


@injectable(lifetime="scoped")
def tenant_context() -> TenantContext:
    """La empresa del scope, para el código que la recibe por inyección. Falla
    solo si alguien la pide sin contexto."""
    return require_tenant()
