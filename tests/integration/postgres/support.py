"""Helpers for the PostgreSQL tests, shared by their fixtures. A plain module:
pytest imports a conftest under its own name, so importing one from a test
gives a second copy."""

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from main import app  # noqa: F401  # registers every event handler
from src.auth.domain.entities import Role, User
from src.auth.infra.models import AuthSessionModel, UserModel
from src.auth.infra.token_service import JwtTokenService
from src.shared.infra.database import Base
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
