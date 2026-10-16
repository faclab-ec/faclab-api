from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from typing import Any

from sqlalchemy.orm import Session
from wireup.ioc.container.async_container import async_container_force_sync_scope
from wireup.ioc.container.sync_container import ScopedSyncContainer

from src.shared.domain.tenant import TenantContext
from src.shared.infra.tenant import tenant_scope


@contextmanager
def create_sync_scope(
    session: Any = None, tenant: TenantContext | None = None
) -> Generator[ScopedSyncContainer, None, None]:
    """Create a synchronous scope from the async wireup container.

    If a session is provided, it will be reused in the new scope,
    ensuring transactional consistency across event handler chains.
    If no session is provided, a new scope with a fresh session is created.

    The scope runs in the current tenant context. A task outside a request
    passes `tenant` to run in that tenant: it is set before the scope opens its
    session and stays until the scope has committed and closed.
    """
    from src import wireup_container

    if wireup_container is None:
        raise RuntimeError("wireup container is not initialized")

    provided: dict[Any, Any] | None = (
        {Session: session} if session is not None else None
    )
    with ExitStack() as stack:
        if tenant is not None:
            stack.enter_context(tenant_scope(tenant))
        yield stack.enter_context(
            async_container_force_sync_scope(wireup_container, provided)
        )
