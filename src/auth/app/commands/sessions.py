import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.auth.app.repositories import AuthSessionRepository
from src.auth.app.services.token_service import TokenPair, TokenService
from src.auth.domain.entities import AuthSession, User
from src.tenancy.app.repositories import MembershipRepository
from src.tenancy.domain.entities import Membership, Tenant


@dataclass(frozen=True)
class OpenedSession:
    """Los tokens de una sesión y la empresa a la que pertenece"""

    pair: TokenPair
    tenant: Tenant


def branch_limit(
    memberships: MembershipRepository, membership: Membership
) -> list[int] | None:
    """Las sucursales a las que la membresía está limitada (claim `bids`); sin
    filas en `user_branch_access`, None: puede entrar a todas"""
    return memberships.branch_ids(membership.require_id()) or None


def open_session(
    session_repo: AuthSessionRepository,
    token_service: TokenService,
    user: User,
    membership: Membership,
    tenant: Tenant,
    now: datetime,
    *,
    branch_ids: Collection[int] | None = None,
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
    pair = token_service.issue_pair(
        user, membership, session.require_id(), refresh_jti, branch_ids=branch_ids
    )
    return OpenedSession(pair=pair, tenant=tenant)
