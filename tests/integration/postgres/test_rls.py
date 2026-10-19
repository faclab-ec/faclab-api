"""Row-level security and database roles (S2.4): the second barrier after the
application's tenant filter. The app connects as faclab_app, which can't bypass
the policies; the relay and the platform lookups as faclab_worker; the tables
belong to faclab_owner. The fixtures look from outside as the superuser."""

import os
from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from config import config
from src.catalog.product.infra.models import ProductModel
from src.invoicing.infra import invoice_messages
from src.sales.infra.models import SaleModel
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.shared.infra.database import Base, create_session_maker, worker_session_maker
from src.shared.infra.events.scope import create_sync_scope
from src.shared.infra.outbox.models import OutboxMessageModel
from src.shared.infra.outbox.relay import OutboxRelay
from src.shared.infra.outbox.writer import OutboxWriter
from tests.integration.postgres.tenants import OTHER_TENANT_RUC, ensure_tenant
from tests.sqlite import load_all_models

load_all_models()

TENANT_SCOPED = sorted(
    mapper.class_.__tablename__
    for mapper in Base.registry.mappers
    if getattr(mapper.class_, "__tenant_scoped__", False)
)
PLATFORM = sorted(set(Base.metadata.tables) - set(TENANT_SCOPED))
POLICY = "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"
INSUFFICIENT_PRIVILEGE = "42501"


class FakePublisher:
    def __init__(self):
        self.sent: list[tuple[str, dict, list]] = []

    def publish(self, topic, value, headers):
        self.sent.append((topic, value, headers))


@pytest.fixture(scope="module")
def app_sessions(pg_engine) -> Iterator[sessionmaker[Session]]:
    """Sessions like the requests': faclab_app, with the tenant setting hook"""
    factory = create_session_maker(os.environ["DATABASE_URL"])
    yield factory
    factory.kw["bind"].dispose()


@pytest.fixture(scope="module")
def owner_engine(pg_engine) -> Iterator[Engine]:
    engine = create_engine(os.environ["DATABASE_URL_MIGRATIONS"])
    yield engine
    engine.dispose()


@pytest.fixture
def tenants(pg_engine) -> tuple[UUID, UUID]:
    return ensure_tenant(pg_engine), ensure_tenant(pg_engine, OTHER_TENANT_RUC)


@pytest.fixture
def products(pg_engine, tenants) -> dict[UUID, int]:
    """One product per tenant, inserted from outside row-level security"""
    ids = {}
    with Session(bind=pg_engine) as session:
        for tenant_id in tenants:
            product = ProductModel(name="Martillo", sku="MAR-1", tenant_id=tenant_id)
            session.add(product)
            session.flush()
            ids[tenant_id] = product.id
        session.commit()
    return ids


def _scalars(engine: Engine, sql: str, **params) -> list:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), params).scalars())


def _row(engine: Engine, sql: str, **params) -> tuple:
    with engine.connect() as conn:
        return tuple(conn.execute(text(sql), params).one())


def _in(tenant_id: UUID):
    return use_tenant(TenantContext(tenant_id, TenantSource.TASK))


def _sqlstate(error: pytest.ExceptionInfo) -> str | None:
    return getattr(error.value.orig, "pgcode", None)


# Roles


def test_the_app_connects_as_faclab_app_without_bypassing_rls(pg_engine):
    assert make_url(config.DB_CONNECTION_STRING).username == "faclab_app"
    with create_sync_scope() as scope:
        user = scope.get(Session).scalar(text("SELECT current_user"))

    attributes = _row(
        pg_engine,
        "SELECT rolsuper, rolbypassrls, pg_has_role(:user, 'faclab_owner', 'MEMBER')"
        " FROM pg_roles WHERE rolname = :user",
        user=user,
    )

    assert user == "faclab_app"
    assert attributes == (False, False, False)


def test_only_the_worker_bypasses_rls(pg_engine):
    with pg_engine.connect() as conn:
        roles = dict(
            conn.execute(
                text(
                    "SELECT rolname, rolbypassrls OR rolsuper FROM pg_roles"
                    " WHERE rolname IN ('faclab_owner', 'faclab_app', 'faclab_worker')"
                )
            ).all()
        )

    assert roles == {"faclab_owner": False, "faclab_app": False, "faclab_worker": True}
    assert make_url(config.DB_WORKER_CONNECTION_STRING).username == "faclab_worker"


def test_faclab_owner_owns_every_table(pg_engine):
    others = _scalars(
        pg_engine,
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        " AND tableowner <> 'faclab_owner'",
    )

    assert others == []


# Catalog: every business table has its policy, the platform ones none


def test_every_tenant_scoped_table_forces_its_policy(pg_engine):
    with pg_engine.connect() as conn:
        forced = set(
            conn.execute(
                text(
                    "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace"
                    " AND relkind = 'r' AND relrowsecurity AND relforcerowsecurity"
                )
            ).scalars()
        )
        policies = conn.execute(
            text(
                "SELECT tablename, policyname, cmd, permissive, roles, qual, with_check"
                " FROM pg_policies WHERE schemaname = 'public' ORDER BY tablename"
            )
        ).all()

    assert len(TENANT_SCOPED) == 35
    assert forced == set(TENANT_SCOPED)
    assert [row.tablename for row in policies] == TENANT_SCOPED
    for row in policies:
        assert (row.policyname, row.cmd, row.permissive) == (
            "tenant_isolation",
            "ALL",
            "PERMISSIVE",
        )
        assert row.roles == ["public"]
        assert row.qual == row.with_check == POLICY


def test_platform_tables_have_no_rls(pg_engine):
    secured = _scalars(
        pg_engine,
        "SELECT relname FROM pg_class WHERE relname = ANY(:names) AND relrowsecurity",
        names=PLATFORM,
    )

    assert set(PLATFORM) >= {
        "tenants",
        "users",
        "memberships",
        "user_branch_access",
        "outbox_messages",
    }
    assert secured == []


# Privileges


@pytest.mark.parametrize("role", ["faclab_app", "faclab_worker"])
def test_no_role_but_the_owner_can_truncate(pg_engine, role):
    # By oid: a name could resolve outside public before the filter applies
    truncatable = _scalars(
        pg_engine,
        "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace"
        " AND relkind = 'r' AND has_table_privilege(:role, oid, 'TRUNCATE')",
        role=role,
    )

    assert truncatable == []


@pytest.mark.parametrize("role", ["faclab_app", "faclab_worker"])
def test_only_the_migrations_touch_alembic_version(pg_engine, role):
    [allowed] = _scalars(
        pg_engine,
        "SELECT has_table_privilege(:role, 'alembic_version',"
        " 'SELECT, INSERT, UPDATE, DELETE')",
        role=role,
    )

    assert allowed is False


def test_the_app_only_inserts_into_the_outbox(pg_engine):
    privileges = _row(
        pg_engine,
        "SELECT has_table_privilege('faclab_app', 'outbox_messages', 'INSERT'),"
        " has_column_privilege('faclab_app', 'outbox_messages', 'id', 'SELECT'),"
        " has_table_privilege('faclab_app', 'outbox_messages', 'SELECT'),"
        " has_column_privilege('faclab_app', 'outbox_messages', 'payload', 'SELECT'),"
        " has_table_privilege('faclab_app', 'outbox_messages', 'UPDATE'),"
        " has_table_privilege('faclab_app', 'outbox_messages', 'DELETE'),"
        " has_table_privilege('faclab_worker', 'outbox_messages', 'SELECT, UPDATE')",
    )

    # INSERT ... RETURNING id needs the id, and nothing else
    assert privileges == (True, True, False, False, False, False, True)


# Behavior


def test_without_a_tenant_the_app_sees_no_rows(app_sessions, products):
    with app_sessions() as session:
        rows = session.execute(text("SELECT * FROM products")).all()

    assert rows == []


def test_a_tenant_sees_only_its_rows(app_sessions, products, tenants):
    a, b = tenants
    with _in(a), app_sessions() as session:
        ids = list(session.scalars(text("SELECT id FROM products")))

    assert ids == [products[a]]


def test_the_owner_is_bound_by_the_policy_too(owner_engine, products):
    assert _scalars(owner_engine, "SELECT id FROM products") == []


def test_the_worker_sees_every_tenant(products):
    with worker_session_maker()() as session:
        ids = set(session.scalars(text("SELECT id FROM products")))

    assert ids == set(products.values())


def test_writing_a_row_of_another_tenant_fails(app_sessions, products, tenants):
    a, b = tenants
    with _in(a), app_sessions() as session, pytest.raises(ProgrammingError) as error:
        session.execute(
            text(
                "INSERT INTO products (tenant_id, name, sku, tax_code, is_active,"
                " is_service, min_stock, reorder_point, created_at)"
                " VALUES (:tenant, 'Intruso', 'X-1', 'VAT_15', true, false, 0, 0, now())"
            ),
            {"tenant": b},
        )

    assert _sqlstate(error) == INSUFFICIENT_PRIVILEGE


def test_moving_a_row_to_another_tenant_fails(app_sessions, products, tenants):
    a, b = tenants
    with _in(a), app_sessions() as session, pytest.raises(ProgrammingError) as error:
        session.execute(
            text("UPDATE products SET tenant_id = :tenant WHERE id = :id"),
            {"tenant": b, "id": products[a]},
        )

    assert _sqlstate(error) == INSUFFICIENT_PRIVILEGE


def test_another_tenants_rows_cannot_be_changed(
    app_sessions, products, tenants, pg_engine
):
    a, b = tenants
    with _in(a), app_sessions() as session:
        updated = session.execute(
            text("UPDATE products SET name = 'Cambiado' WHERE id = :id"),
            {"id": products[b]},
        ).rowcount
        deleted = session.execute(
            text("DELETE FROM products WHERE id = :id"), {"id": products[b]}
        ).rowcount
        session.commit()

    assert (updated, deleted) == (0, 0)
    assert _scalars(
        pg_engine, "SELECT name FROM products WHERE id = :id", id=products[b]
    ) == ["Martillo"]


def test_a_connection_that_had_a_tenant_sees_no_rows(app_sessions, products, tenants):
    a, _ = tenants
    with app_sessions.kw["bind"].connect() as conn:
        with conn.begin():
            conn.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(a)},
            )
            mine = conn.execute(text("SELECT count(*) FROM products")).scalar()
        # Same connection, next transaction: the setting is '' now, not NULL,
        # and the policy's nullif turns it into no rows instead of an error
        with conn.begin():
            setting = conn.scalar(text("SELECT current_setting('app.tenant_id', true)"))
            rows = conn.execute(text("SELECT * FROM products")).all()

    assert mine == 1
    assert setting == ""
    assert rows == []


# Outbox and platform lookups


def _queue(app_sessions, tenant_id: UUID, event_id: str) -> None:
    with _in(tenant_id), app_sessions() as session:
        OutboxWriter(session).add("sales.confirmed", {"id": event_id}, "Test", event_id)
        session.commit()


def test_the_app_cannot_read_the_outbox(app_sessions, tenants):
    a, _ = tenants
    _queue(app_sessions, a, "event-a")

    with _in(a), app_sessions() as session, pytest.raises(ProgrammingError) as error:
        session.scalars(select(OutboxMessageModel)).all()

    assert _sqlstate(error) == INSUFFICIENT_PRIVILEGE


def test_the_worker_relays_every_tenants_messages(app_sessions, tenants):
    a, b = tenants
    _queue(app_sessions, a, "event-a")
    _queue(app_sessions, b, "event-b")
    publisher = FakePublisher()

    assert OutboxRelay(worker_session_maker(), publisher).publish_pending() == 2

    sent = {value["id"]: dict(headers) for _, value, headers in publisher.sent}
    assert sent["event-a"]["faclab-tenant-id"] == str(a).encode()
    assert sent["event-b"]["faclab-tenant-id"] == str(b).encode()


def test_the_relay_cannot_run_as_the_app(app_sessions, tenants):
    a, _ = tenants
    _queue(app_sessions, a, "event-a")

    with pytest.raises(ProgrammingError) as error:
        OutboxRelay(app_sessions, FakePublisher()).publish_pending()

    assert _sqlstate(error) == INSUFFICIENT_PRIVILEGE


def test_the_tenant_of_a_sale_is_a_platform_lookup(app_sessions, pg_engine, tenants):
    _, b = tenants
    with Session(bind=pg_engine) as session:
        sale = SaleModel(tenant_id=b)
        session.add(sale)
        session.commit()
        sale_id = sale.id

    with app_sessions() as session:
        hidden = session.scalar(
            select(SaleModel.tenant_id).where(SaleModel.id == sale_id)
        )

    assert hidden is None
    assert invoice_messages._tenant_of_sale(sale_id) == b
