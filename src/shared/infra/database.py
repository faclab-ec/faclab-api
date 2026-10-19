import functools
from collections.abc import Iterable, Iterator
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, ForeignKey, Uuid, create_engine, event, text
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    SessionTransaction,
    UOWTransaction,
    mapped_column,
    sessionmaker,
)
from wireup import injectable

from src.shared.domain.exceptions import BaseError
from src.shared.domain.tenant import (
    TenantMismatchError,
    current_tenant_id,
    require_tenant,
)
from src.shared.infra.adapters import OpenTelemetry


class Base(DeclarativeBase):
    pass


class TenantScoped:
    """Mixin of every business table: its rows belong to one tenant.

    The base repository assigns and filters `tenant_id` from the context, and
    `assign_tenant` assigns it to any other row written through the ORM. A
    unique constraint of the table starts with `tenant_id`, and a foreign key
    to a row that must be of the same tenant is composite:
    `(tenant_id, x_id) -> x (tenant_id, id)`.
    """

    __tenant_scoped__ = True

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


def create_session_maker(
    connection_string: str, traced: bool = False
) -> sessionmaker[Session]:
    """`traced` adds a span per query (with OTel enabled). Only the requests'
    engine is traced: the outbox relay and the readiness check poll every few
    seconds and would bury the queries that matter."""
    if not connection_string:
        raise ValueError("Database connection string cannot be empty")

    engine = create_engine(connection_string)
    if traced:
        OpenTelemetry().instrument_engine(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    event.listen(factory, "after_begin", set_tenant_setting)
    event.listen(factory, "before_flush", assign_tenant)
    return factory


@functools.cache
def worker_session_maker() -> sessionmaker[Session]:
    """Sessions as faclab_worker, which bypasses row-level security (S2.4): for
    the outbox relay and the platform lookups that run outside every tenant,
    never for a request. One engine per process."""
    from config import config

    return create_session_maker(config.DB_WORKER_CONNECTION_STRING)


def set_tenant_setting(
    _session: Session, _transaction: SessionTransaction, connection: Connection
) -> None:
    """Each transaction starts with `SET LOCAL app.tenant_id` (as `set_config`,
    which takes parameters) when there is a tenant context: the value dies with
    the transaction, so it never leaks to a request that reuses the pooled
    connection. Row-Level Security reads it (S2.4)."""
    tenant_id = current_tenant_id()
    if tenant_id is None or connection.dialect.name != "postgresql":
        return
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def assign_tenant(
    session: Session, _flush_context: UOWTransaction, _instances: Iterable[Any] | None
) -> None:
    """Every new row of a tenant-scoped model gets the context's tenant before
    it is inserted, also when it doesn't come through the base repository (the
    seed, a relationship, a script). One that carries another tenant is
    rejected, and without a context nothing is written."""
    for instance in session.new:
        if not getattr(type(instance), "__tenant_scoped__", False):
            continue
        tenant_id = require_tenant(f"writing {type(instance).__name__}").tenant_id
        if instance.tenant_id is None:
            instance.tenant_id = tenant_id
        elif instance.tenant_id != tenant_id:
            raise TenantMismatchError(instance.tenant_id, tenant_id)


def create_session_factory(connection_string: str):
    _factory = create_session_maker(connection_string, traced=True)

    @injectable(lifetime="scoped")
    def get_db_session() -> Iterator[Session]:
        session = _factory()
        try:
            yield session
            session.commit()
        except Exception as exc:
            if isinstance(exc, BaseError) and exc.commit_transaction:
                session.commit()
            else:
                session.rollback()
            raise
        finally:
            session.close()

    return get_db_session
