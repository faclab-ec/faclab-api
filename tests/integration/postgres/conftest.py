"""Fixtures for tests that run against a real PostgreSQL database.

These tests only run when TEST_DATABASE_URL is set (`make test-integration`);
otherwise every test marked `postgres` is skipped. Once per session the roles
are bootstrapped, the database is recreated owned by faclab_owner and Alembic
migrates it as that role; every test starts from empty tables.

`pg_engine` and `db_session` connect as the superuser of TEST_DATABASE_URL:
fixtures and checks see every tenant's rows, while the app runs as faclab_app
under row-level security (S2.4).
"""

import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from main import app
from src.auth.domain.entities import Role, User
from src.auth.infra.models import AuthSessionModel, UserModel
from src.auth.infra.token_service import JwtTokenService
from src.shared.infra.database import Base
from src.shared.infra.db_roles import RoleUrls, bootstrap
from src.shared.infra.events.event_bus import EventBus
from src.tenancy.domain.entities import Membership
from src.tenancy.infra.models import MembershipModel
from tests.integration.postgres.tenants import ensure_tenant

ROOT = Path(__file__).resolve().parents[3]

# Importing `main` registers every event handler. Some unit tests clear the
# EventBus, so keep a copy and restore it before each Postgres test.
_SUBSCRIBERS = {
    event: list(handlers) for event, handlers in EventBus._subscribers.items()
}
_ACCEPTS_SESSION = dict(EventBus._accepts_session)


def _test_database_url():
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if not (url.database or "").endswith("_test"):
        raise RuntimeError(
            "TEST_DATABASE_URL must name a database ending in '_test'; "
            f"refusing to recreate '{url.database}'"
        )
    return url


def _role_urls(url) -> RoleUrls:
    """The roles of the app, the worker and the migrations, on the test database"""
    roles = RoleUrls.parse(
        admin=os.environ["TEST_DATABASE_URL"],
        owner=os.environ["DATABASE_URL_MIGRATIONS"],
        app=os.environ["DATABASE_URL"],
        worker=os.environ["DATABASE_URL_WORKER"],
    )
    if roles.database != url.database:
        raise RuntimeError("the role URLs must name the database of TEST_DATABASE_URL")
    return roles


def _drop_database(url) -> None:
    maintenance = create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    with maintenance.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
    maintenance.dispose()


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine]:
    url = _test_database_url()
    roles = _role_urls(url)
    _drop_database(url)
    # Creates the database owned by faclab_owner
    bootstrap(roles)
    # Run Alembic in a subprocess so its logging config doesn't leak into pytest.
    # The root conftest already pointed DATABASE_URL_MIGRATIONS at the owner.
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    engine = create_engine(url)
    yield engine
    engine.dispose()
    _drop_database(url)


def truncate_all(engine: Engine) -> None:
    """Empty every table (as the superuser: TRUNCATE ignores row-level security)"""
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def restore_event_bus() -> None:
    EventBus._subscribers.clear()
    EventBus._subscribers.update(
        {event: list(handlers) for event, handlers in _SUBSCRIBERS.items()}
    )
    EventBus._accepts_session.clear()
    EventBus._accepts_session.update(_ACCEPTS_SESSION)


@pytest.fixture(autouse=True)
def _clean_state(pg_engine: Engine) -> Iterator[None]:
    """Empty every table and restore the event handlers before each test."""
    truncate_all(pg_engine)
    restore_event_bus()
    yield


@pytest.fixture
def db_session(pg_engine: Engine) -> Iterator[Session]:
    session = Session(bind=pg_engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(pg_engine: Engine) -> TestClient:
    # Not used as a context manager: the lifespan only closes Kafka and OTEL.
    return TestClient(app)


@pytest.fixture
def tenant(pg_engine: Engine) -> UUID:
    """The default tenant, where `auth_headers` users work unless told otherwise"""
    return ensure_tenant(pg_engine)


def issue_headers(
    engine: Engine,
    role: Role = Role.ADMIN,
    full_name: str | None = None,
    tenant_id: UUID | None = None,
    username: str | None = None,
) -> dict[str, str]:
    """Bearer headers for a new persisted user with the given role in a tenant
    (the default one unless `tenant_id` is given). Usernames are global."""
    tenant_id = tenant_id or ensure_tenant(engine)
    username = username or f"{role.name.lower()}-test"
    with Session(bind=engine) as session:
        model = UserModel(
            username=username,
            email=f"{username}@test.local",
            password_hash="not-used",
            is_active=True,
            must_change_password=False,
            full_name=full_name,
        )
        session.add(model)
        session.flush()
        session.add(
            MembershipModel(
                tenant_id=tenant_id, user_id=model.id, role=int(role), active=True
            )
        )
        auth_session = AuthSessionModel(
            user_id=model.id,
            tenant_id=tenant_id,
            expires_at=datetime.now() + timedelta(days=1),
            refresh_jti="test-jti",
        )
        session.add(auth_session)
        session.commit()
        session_id = auth_session.id
        user = User(
            id=model.id,
            username=model.username,
            email=model.email,
            password_hash=model.password_hash,
            full_name=full_name,
        )
    membership = Membership(tenant_id=tenant_id, user_id=model.id, role=role)
    token = (
        JwtTokenService()
        .issue_pair(user, membership, session_id, "test-jti")
        .access_token
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers(pg_engine: Engine) -> Callable[..., dict[str, str]]:
    """Return bearer headers for a persisted user with the given role in a
    tenant (the default one unless `tenant_id` is given)."""

    def _headers(*args, **kwargs) -> dict[str, str]:
        return issue_headers(pg_engine, *args, **kwargs)

    return _headers


@pytest.fixture
def admin(auth_headers) -> dict[str, str]:
    return auth_headers(Role.ADMIN)
