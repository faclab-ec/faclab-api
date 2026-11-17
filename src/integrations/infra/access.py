"""The state of the integration clients, as `AuthMiddleware` checks their
tokens (S6.2).

Every request with an integration's token needs its client's current state:
whether it was revoked, which secrets still work, its scopes, branches and
networks. It is read with a session of its own (faclab_app, under row-level
security in the token's tenant) and kept in memory for at most
INTEGRATION_STATUS_CACHE_SECONDS, so each process sees a revocation within
that time without a query per request. The usage of each request is counted
in a short transaction of its own, apart from the request's.
"""

import functools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from config import config
from src.auth.app.services.integration_access import IntegrationAccess
from src.auth.app.services.token_service import ClientTokenClaims
from src.auth.domain.principals import IntegrationPrincipal
from src.auth.domain.scopes import Scope
from src.integrations.domain.credentials import IntegrationEnvironment
from src.integrations.domain.entities import IntegrationClientStatus, allows_ip
from src.integrations.infra.models import ClientSecretModel, IntegrationClientModel
from src.integrations.infra.repositories import (
    SqlAlchemyIntegrationUsageRepository,
    tenant_of_client,
)
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.shared.infra.database import app_session_maker
from src.shared.infra.tenant import tenant_criteria

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ClientState:
    client_id: int
    name: str
    status: IntegrationClientStatus
    environment: IntegrationEnvironment
    scopes: frozenset[Scope]
    branch_ids: frozenset[int] | None
    allowed_ips: tuple[str, ...] | None
    # The secrets not revoked, with when they expire (None: never)
    secrets: dict[int, datetime | None]

    def secret_active(self, secret_id: int, now: datetime) -> bool:
        if secret_id not in self.secrets:
            return False
        expires_at = self.secrets[secret_id]
        return expires_at is None or expires_at > now


class CachedIntegrationAccess(IntegrationAccess):
    def __init__(
        self,
        session_maker: Callable[[], sessionmaker[Session]],
        *,
        environment: IntegrationEnvironment,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
    ):
        # A factory: the engine is created on the first integration request
        self._session_maker = session_maker
        self._environment = environment
        self._ttl = ttl_seconds
        self._clock = clock
        self._now = now
        self._lock = threading.Lock()
        self._states: dict[tuple[UUID, str], tuple[float, ClientState | None]] = {}
        # client_id → tenant never changes: kept for the life of the process
        self._tenants: dict[str, UUID] = {}

    def principal(
        self, claims: ClientTokenClaims, ip: str | None
    ) -> IntegrationPrincipal | None:
        state = self._state(claims.tid, claims.public_id)
        reason = self._refusal(state, claims, ip)
        if reason is not None or state is None:
            logger.info(
                "integration_token_rejected",
                client_id=claims.public_id,
                reason=reason or "unknown client",
            )
            return None
        return IntegrationPrincipal(
            client_id=state.client_id,
            public_id=claims.public_id,
            name=state.name,
            tenant_id=claims.tid,
            # Taking a scope or a branch away applies to the tokens it has
            scopes=claims.scopes & state.scopes,
            branch_ids=_narrow(claims.bids, state.branch_ids),
        )

    def record_request(
        self, principal: IntegrationPrincipal, status_code: int, ip: str | None
    ) -> None:
        now = self._now()
        context = TenantContext(principal.tenant_id, TenantSource.REQUEST)
        try:
            with use_tenant(context), self._session_maker()() as session:
                SqlAlchemyIntegrationUsageRepository(session).count(
                    principal.client_id,
                    at=now,
                    ip=ip,
                    requests=1,
                    errors=1 if status_code >= 400 else 0,
                )
                session.execute(
                    update(IntegrationClientModel)
                    .where(
                        *tenant_criteria(IntegrationClientModel),
                        IntegrationClientModel.id == principal.client_id,
                    )
                    .values(last_used_at=now)
                )
                session.commit()
        except Exception:
            logger.exception("integration_usage_failed", client_id=principal.public_id)

    def tenant_of(self, public_id: str) -> UUID | None:
        """The tenant of a client_id, for the token endpoint"""
        tenant_id = self._tenants.get(public_id)
        if tenant_id is not None:
            return tenant_id
        with self._session_maker()() as session:
            tenant_id = tenant_of_client(session, public_id)
        if tenant_id is not None:
            # Unknown ones aren't kept: anyone can send made-up client_ids
            self._tenants[public_id] = tenant_id
        return tenant_id

    def _refusal(
        self, state: ClientState | None, claims: ClientTokenClaims, ip: str | None
    ) -> str | None:
        if state is None:
            return "unknown client"
        if state.status is not IntegrationClientStatus.ACTIVE:
            return "client revoked"
        if state.environment is not self._environment:
            return f"client of the {state.environment} environment"
        if not state.secret_active(claims.secret_id, self._now()):
            return "secret revoked or expired"
        if not allows_ip(state.allowed_ips, ip):
            return "address not allowed"
        return None

    def _state(self, tenant_id: UUID, public_id: str) -> ClientState | None:
        key = (tenant_id, public_id)
        with self._lock:
            cached = self._states.get(key)
        if cached is not None and cached[0] > self._clock():
            return cached[1]
        state = self._load(tenant_id, public_id)
        with self._lock:
            self._states[key] = (self._clock() + self._ttl, state)
        return state

    def _load(self, tenant_id: UUID, public_id: str) -> ClientState | None:
        # The context is set before the session begins, so its transaction
        # runs `SET LOCAL app.tenant_id` (row-level security)
        context = TenantContext(tenant_id, TenantSource.REQUEST)
        with use_tenant(context), self._session_maker()() as session:
            client = session.scalars(
                select(IntegrationClientModel).where(
                    *tenant_criteria(IntegrationClientModel),
                    IntegrationClientModel.public_id == public_id,
                )
            ).first()
            if client is None:
                return None
            secrets = session.execute(
                select(ClientSecretModel.id, ClientSecretModel.expires_at).where(
                    *tenant_criteria(ClientSecretModel),
                    ClientSecretModel.client_id == client.id,
                    ClientSecretModel.revoked_at.is_(None),
                )
            ).all()
            return ClientState(
                client_id=client.id,
                name=client.name,
                status=IntegrationClientStatus(client.status),
                environment=IntegrationEnvironment(client.environment),
                scopes=frozenset(
                    Scope(name)
                    for name in client.scopes
                    if name in Scope._value2member_map_
                ),
                branch_ids=frozenset(client.branch_ids) if client.branch_ids else None,
                allowed_ips=tuple(client.allowed_ips) if client.allowed_ips else None,
                secrets={row.id: row.expires_at for row in secrets},
            )


def _narrow(
    token: frozenset[int] | None, client: frozenset[int] | None
) -> frozenset[int] | None:
    """The branches both allow; None on one side is no limit"""
    if token is None:
        return client
    if client is None:
        return token
    return token & client


@functools.cache
def integration_access() -> CachedIntegrationAccess:
    """The one of the process: `AuthMiddleware` and the token endpoint share
    its caches"""
    return CachedIntegrationAccess(
        app_session_maker,
        environment=IntegrationEnvironment(config.INTEGRATION_ENVIRONMENT),
        ttl_seconds=config.INTEGRATION_STATUS_CACHE_SECONDS,
    )
