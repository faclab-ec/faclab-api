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
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from main import app
from src.auth.domain.entities import Role
from src.shared.infra.db_roles import RoleUrls, bootstrap
from tests.integration.postgres.support import (
    ROOT,
    issue_headers,
    restore_event_bus,
    truncate_all,
)
from tests.integration.postgres.tenants import ensure_tenant


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
