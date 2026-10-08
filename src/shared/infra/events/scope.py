from typing import Any

from sqlalchemy.orm import Session
from wireup.ioc.container.async_container import async_container_force_sync_scope
from wireup.ioc.container.sync_container import ScopedSyncContainer


def create_sync_scope(session: Any = None) -> ScopedSyncContainer:
    """Create a synchronous scope from the async wireup container.

    If a session is provided, it will be reused in the new scope,
    ensuring transactional consistency across event handler chains.
    If no session is provided, a new scope with a fresh session is created.
    """
    from src import wireup_container

    if wireup_container is None:
        raise RuntimeError("wireup container is not initialized")

    provided: dict[Any, Any] | None = (
        {Session: session} if session is not None else None
    )
    return async_container_force_sync_scope(wireup_container, provided)
