"""In-memory SQLite databases for the tests that run real SQL without PostgreSQL."""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from src.shared.infra.database import Base, create_session_maker
from src.tenancy.infra.models import TenantModel
from tests.conftest import TEST_TENANT_ID


def sqlite_session(models: Iterable[Any], foreign_keys: bool = False) -> Session:
    """A session over a new in-memory database with the tables of `models` plus
    `tenants`, which holds the test tenant (the one `in_tenant` sets). It comes
    from the app's session maker, so new tenant-scoped rows get the context's
    tenant. `foreign_keys` makes SQLite enforce them."""
    factory = create_session_maker("sqlite://")
    engine = factory.kw["bind"]
    if foreign_keys:

        @event.listens_for(engine, "connect")
        def _enable_fks(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    names = [TenantModel.__tablename__, *(model.__tablename__ for model in models)]
    tables = [Base.metadata.tables[name] for name in names]
    Base.metadata.create_all(engine, tables=tables)
    session = factory()
    session.add(
        TenantModel(id=TEST_TENANT_ID, ruc="1799999990001", legal_name="Empresa")
    )
    session.commit()
    return session
