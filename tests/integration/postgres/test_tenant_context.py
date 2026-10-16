"""Tenant context against PostgreSQL: every transaction of an authenticated
request runs with `app.tenant_id` = the token's `tid`, the value dies with the
transaction, and a tenant-scoped repository never crosses tenants."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker
from wireup import Injected
from wireup.integration.fastapi import setup as wireup_fastapi_setup

import main
from src.auth.domain.entities import Role
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.shared.infra.database import create_session_maker
from tests.integration.postgres.tenants import OTHER_TENANT_RUC, ensure_tenant
from tests.tenant_notes import Note, NoteMapper, NoteModel, NoteRepository, ScratchBase

SETTING = text("SELECT current_setting('app.tenant_id', true)")
BACKEND = text("SELECT pg_backend_pid()")


@pytest.fixture
def probe(pg_engine: Engine) -> TestClient:
    """An app with the API's middlewares and DI container whose only route
    reads `app.tenant_id` in two transactions of the request session."""
    app = FastAPI()

    @app.get("/probe")
    def read_setting(session: Injected[Session]) -> dict:
        first = session.scalar(SETTING)
        session.commit()
        return {"transactions": [first, session.scalar(SETTING)]}

    main.add_middlewares(app)
    wireup_fastapi_setup(main.wireup_container, app)
    return TestClient(app)


def test_each_transaction_of_a_request_runs_in_the_token_tenant(
    probe, auth_headers, tenant, pg_engine
):
    other = ensure_tenant(pg_engine, OTHER_TENANT_RUC)

    in_default = probe.get("/probe", headers=auth_headers(Role.CASHIER)).json()
    in_other = probe.get(
        "/probe",
        headers=auth_headers(Role.CASHIER, tenant_id=other, username="other-cashier"),
    ).json()

    assert in_default == {"transactions": [str(tenant), str(tenant)]}
    assert in_other == {"transactions": [str(other), str(other)]}


def test_an_anonymous_request_has_no_tenant_setting(probe):
    # After a connection once had the setting, PostgreSQL answers '' instead of NULL
    assert not any(probe.get("/probe").json()["transactions"])


def test_the_setting_dies_with_its_transaction(pg_engine):
    factory = create_session_maker(pg_engine.url.render_as_string(hide_password=False))
    tenant_id = UUID("00000000-0000-4000-8000-0000000000a1")

    with factory() as session:
        with use_tenant(TenantContext(tenant_id, TenantSource.TASK)):
            backend = session.scalar(BACKEND)
            assert session.scalar(SETTING) == str(tenant_id)
            session.commit()
        # Same pooled connection, new transaction without a context. PostgreSQL
        # answers '' rather than NULL once the connection had the setting, so
        # RLS policies must use nullif(..., '') (S2.4)
        assert session.scalar(BACKEND) == backend
        assert session.scalar(SETTING) == ""
    factory.kw["bind"].dispose()


@pytest.fixture
def notes(pg_engine: Engine) -> Iterator[sessionmaker[Session]]:
    table = ScratchBase.metadata.tables[NoteModel.__tablename__]
    ScratchBase.metadata.create_all(pg_engine, tables=[table])
    yield sessionmaker(bind=pg_engine)
    ScratchBase.metadata.drop_all(pg_engine, tables=[table])


def test_a_tenant_scoped_repository_never_crosses_tenants(notes, tenant, pg_engine):
    other = ensure_tenant(pg_engine, OTHER_TENANT_RUC)
    in_default = TenantContext(tenant, TenantSource.TASK)
    in_other = TenantContext(other, TenantSource.TASK)

    with notes() as session:
        repo = NoteRepository(session, NoteMapper())
        with use_tenant(in_default):
            mine = repo.create(Note(title="shared"))
        with use_tenant(in_other):
            theirs = repo.create(Note(title="shared"))
        session.commit()

        with use_tenant(in_default):
            assert repo.get_by_id(theirs.require_id()) is None
            assert repo.filter_by(title="shared") == [mine]
            assert repo.count_by() == 1
            with pytest.raises(NotFoundError):
                repo.update(Note(id=theirs.id, title="taken"))
            with pytest.raises(NotFoundError):
                repo.delete(theirs.require_id())

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tenant_id, title FROM tenant_scoped_notes ORDER BY id")
        ).all()
    assert [tuple(row) for row in rows] == [(tenant, "shared"), (other, "shared")]
