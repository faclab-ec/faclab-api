"""Empresa (tenant) en la que corre el código.

El contexto se fija al entrar: desde el token en cada request (`AuthMiddleware`),
desde el mensaje en cada consumidor de Kafka y explícitamente en cada tarea
(`create_sync_scope(tenant=...)`). Con él, el repositorio base asigna y filtra
`tenant_id`, la sesión ejecuta `SET LOCAL app.tenant_id` y cada evento de
dominio lleva su empresa.

Vive en un `ContextVar`: lo heredan las tareas de asyncio y el threadpool de
FastAPI, pero no un hilo nuevo (relay, consumidor), que debe fijarlo por su
cuenta. Fuera de las pruebas se entra con `src.shared.infra.tenant.tenant_scope`,
que además lo agrega a los logs y al span.
"""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class TenantSource(StrEnum):
    """De dónde salió la empresa del contexto"""

    REQUEST = "request"  # el `tid` del access token
    MESSAGE = "message"  # el mensaje de Kafka
    TASK = "task"  # una tarea o script que la elige explícitamente


@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    source: TenantSource
    user_id: int | None = None
    branch_id: int | None = None  # Sucursal, desde S2.5


class TenantContextRequiredError(RuntimeError):
    """Código que necesita una empresa corrió sin contexto: es un error de
    programación (una ruta pública o un hilo que no lo fijó), no del cliente."""

    def __init__(self, action: str = "this operation"):
        super().__init__(f"{action} requires a tenant context")


class TenantMismatchError(RuntimeError):
    """Un dato trae una empresa distinta a la del contexto. La empresa sale
    siempre del contexto, nunca del cuerpo ni de la entidad."""

    def __init__(self, given: UUID, expected: UUID):
        super().__init__(f"tenant {given} does not match the context tenant {expected}")


_current: ContextVar[TenantContext | None] = ContextVar("tenant_context", default=None)


def current_tenant() -> TenantContext | None:
    return _current.get()


def current_tenant_id() -> UUID | None:
    context = _current.get()
    return context.tenant_id if context is not None else None


def require_tenant(action: str = "this operation") -> TenantContext:
    context = _current.get()
    if context is None:
        raise TenantContextRequiredError(action)
    return context


@contextmanager
def use_tenant(context: TenantContext) -> Generator[TenantContext, None, None]:
    """Fija la empresa mientras dura el bloque y restaura la anterior al salir"""
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)
