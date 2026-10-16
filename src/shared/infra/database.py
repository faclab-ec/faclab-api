from collections.abc import Iterator

from sqlalchemy import Connection, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, SessionTransaction, sessionmaker
from wireup import injectable

from src.shared.domain.exceptions import BaseError
from src.shared.domain.tenant import current_tenant_id
from src.shared.infra.adapters import OpenTelemetry


class Base(DeclarativeBase):
    pass


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
    return factory


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
