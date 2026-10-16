import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.auth.app.repositories import AuthSessionRepository
from src.auth.app.services.token_service import TokenPair, TokenService
from src.auth.domain.entities import AuthSession, User
from src.tenancy.domain.entities import Membership, Tenant


@dataclass(frozen=True)
class OpenedSession:
    """Los tokens de una sesión y la empresa a la que pertenece"""

    pair: TokenPair
    tenant: Tenant


def open_session(
    session_repo: AuthSessionRepository,
    token_service: TokenService,
    user: User,
    membership: Membership,
    tenant: Tenant,
    now: datetime,
) -> OpenedSession:
    """Abre una sesión del usuario en la empresa de la membresía y emite sus
    tokens"""
    refresh_jti = uuid.uuid4().hex
    session = session_repo.create(
        AuthSession(
            user_id=user.require_id(),
            tenant_id=membership.tenant_id,
            expires_at=now + timedelta(seconds=token_service.refresh_ttl_seconds),
            refresh_jti=refresh_jti,
            refreshed_at=now,
        )
    )
    pair = token_service.issue_pair(user, membership, session.require_id(), refresh_jti)
    return OpenedSession(pair=pair, tenant=tenant)
