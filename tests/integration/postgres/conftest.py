"""Fixtures for tests that run against a real PostgreSQL database.

These tests only run when TEST_DATABASE_URL is set (`make test-integration`);
otherwise every test marked `postgres` is skipped. The database is recreated and
migrated with Alembic once per session, and every test starts from empty tables.
"""

import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path

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
from src.shared.infra.events.event_bus import EventBus

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


def _recreate_database(url) -> None:
    maintenance = create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    with maintenance.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    maintenance.dispose()


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
    _recreate_database(url)
    # Run Alembic in a subprocess so its logging config doesn't leak into pytest.
    # The root conftest already pointed DATABASE_URL at the test database.
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
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with pg_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))

    EventBus._subscribers.clear()
    EventBus._subscribers.update(
        {event: list(handlers) for event, handlers in _SUBSCRIBERS.items()}
    )
    EventBus._accepts_session.clear()
    EventBus._accepts_session.update(_ACCEPTS_SESSION)
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
def auth_headers(pg_engine: Engine) -> Callable[..., dict[str, str]]:
    """Return bearer headers for a persisted user with the given role."""

    def _headers(role: Role = Role.ADMIN) -> dict[str, str]:
        with Session(bind=pg_engine) as session:
            model = UserModel(
                username=f"{role.name.lower()}-test",
                email=f"{role.name.lower()}@test.local",
                password_hash="not-used",
                role=int(role),
                is_active=True,
                must_change_password=False,
            )
            session.add(model)
            session.flush()
            auth_session = AuthSessionModel(
                user_id=model.id, expires_at=datetime.now() + timedelta(days=1)
            )
            session.add(auth_session)
            session.commit()
            session_id = auth_session.id
            user = User(
                id=model.id,
                username=model.username,
                email=model.email,
                password_hash=model.password_hash,
                role=role,
            )
        token = JwtTokenService().issue_pair(user, session_id).access_token
        return {"Authorization": f"Bearer {token}"}

    return _headers


@pytest.fixture
def admin(auth_headers) -> dict[str, str]:
    return auth_headers(Role.ADMIN)
