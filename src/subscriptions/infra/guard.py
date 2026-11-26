"""Read-only mode of a tenant whose subscription isn't active (S8.4).

A suspended or cancelled subscription, or a trial past its end, lets the
tenant read and nothing else: `SubscriptionGuardMiddleware` answers 403
`SUBSCRIPTION_READ_ONLY` to every request that isn't a GET under the admin,
POS and public APIs, except the ones in `WRITE_ALLOWED`. Login, refresh,
logout, password change and the OAuth token are outside those prefixes. The
worker, the Kafka consumers and the outbox relay don't go through HTTP, so the
invoicing of what the tenant already sold goes on.

The status is read with a session of its own (faclab_app, in the request's
tenant) and kept for at most SUBSCRIPTION_STATUS_CACHE_SECONDS, like the state
of the integration clients: a change applies within that time.
"""

import functools
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.shared.domain.tenant import (
    TenantContext,
    TenantSource,
    current_tenant,
    use_tenant,
)
from src.shared.infra.middlewares import build_error_response
from src.shared.infra.tenant import tenant_criteria
from src.subscriptions.domain.entities import Subscription, SubscriptionStatus
from src.subscriptions.domain.exceptions import SubscriptionReadOnlyError
from src.subscriptions.infra.models import SubscriptionModel

logger = structlog.get_logger(__name__)

GUARDED_PREFIXES = ("/api/admin/", "/api/pos/", "/api/v1/")
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# The writes a read-only tenant may still do (method, route). A test checks
# each one is a route of the API
WRITE_ALLOWED: tuple[tuple[str, str], ...] = (
    # Queries sent as POST
    ("POST", "/api/pos/prices/resolve"),
    # The fiscal follow-up of what was already sold: the invoice of a confirmed
    # sale sent again, a credit note asked again, the invoice authorized on a
    # cancelled sale credited
    ("POST", "/api/admin/sales/{sale_id}/request-invoice"),
    ("POST", "/api/admin/credit-notes/{credit_note_id}/request-again"),
    ("POST", "/api/admin/invoice-discrepancies/{discrepancy_id}/credit-note"),
    # The Z closing of the shift that was open, to balance its cash
    ("POST", "/api/pos/shifts/{shift_id}/close"),
    # The company's own data out, whatever happens to the subscription (S8.7)
    ("POST", "/api/admin/data-exports"),
    # Taking access away
    ("POST", "/api/admin/users/{user_id}/deactivate"),
    ("POST", "/api/admin/integrations/{id}/revoke"),
    ("POST", "/api/admin/integrations/{id}/secrets/{secret_id}/revoke"),
    ("POST", "/api/admin/webhook-endpoints/{id}/disable"),
    ("DELETE", "/api/admin/webhook-endpoints/{id}"),
    ("POST", "/api/v1/webhook-endpoints/{endpoint_id}/disable"),
    ("DELETE", "/api/v1/webhook-endpoints/{endpoint_id}"),
)


def _route_pattern(path: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^}]+\})", path)
    return re.compile(
        "".join("[^/]+" if part.startswith("{") else re.escape(part) for part in parts)
        + "/?"
    )


_ALLOWED = tuple((method, _route_pattern(path)) for method, path in WRITE_ALLOWED)


def is_guarded(method: str, path: str) -> bool:
    """Whether a read-only tenant is refused this request"""
    if method in READ_METHODS or not path.startswith(GUARDED_PREFIXES):
        return False
    return not any(
        allowed == method and pattern.fullmatch(path) for allowed, pattern in _ALLOWED
    )


class CachedSubscriptionAccess:
    def __init__(
        self,
        session_maker: Callable[[], sessionmaker[Session]],
        *,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
    ):
        # A factory: the engine is created on the first write request
        self._session_maker = session_maker
        self._ttl = ttl_seconds
        self._clock = clock
        self._now = now
        self._lock = threading.Lock()
        self._subscriptions: dict[UUID, tuple[float, Subscription | None]] = {}

    def allows_writes(self, tenant_id: UUID) -> bool:
        subscription = self._subscription(tenant_id)
        # No subscription: the default plan, active
        return subscription is None or subscription.allows_writes(self._now())

    def forget(self) -> None:
        with self._lock:
            self._subscriptions.clear()

    def _subscription(self, tenant_id: UUID) -> Subscription | None:
        with self._lock:
            cached = self._subscriptions.get(tenant_id)
        if cached is not None and cached[0] > self._clock():
            return cached[1]
        subscription = self._load(tenant_id)
        with self._lock:
            self._subscriptions[tenant_id] = (self._clock() + self._ttl, subscription)
        return subscription

    def _load(self, tenant_id: UUID) -> Subscription | None:
        # The context is set before the session begins: its transaction runs
        # `SET LOCAL app.tenant_id` (row-level security)
        context = TenantContext(tenant_id, TenantSource.REQUEST)
        with use_tenant(context), self._session_maker()() as session:
            row = session.execute(
                select(
                    SubscriptionModel.plan_id,
                    SubscriptionModel.status,
                    SubscriptionModel.trial_ends_at,
                ).where(*tenant_criteria(SubscriptionModel))
            ).first()
        if row is None:
            return None
        return Subscription(
            plan_id=row.plan_id,
            status=SubscriptionStatus(row.status),
            trial_ends_at=row.trial_ends_at,
        )


class SubscriptionGuardMiddleware:
    """Inside `AuthMiddleware` (it needs the request's tenant) and outside the
    error handler. Without an access (PLAN_ENFORCEMENT_ENABLED=false) it lets
    everything through"""

    def __init__(self, app: ASGIApp, access: CachedSubscriptionAccess | None):
        self.app = app
        self.access = access

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        context = current_tenant()
        if (
            self.access is None
            or scope["type"] != "http"
            or context is None
            or not is_guarded(scope["method"], scope["path"])
        ):
            await self.app(scope, receive, send)
            return
        try:
            allowed = await run_in_threadpool(
                self.access.allows_writes, context.tenant_id
            )
        except Exception:
            # The request's own transaction will fail if the database does
            logger.exception("subscription_check_failed")
            allowed = True
        if allowed:
            await self.app(scope, receive, send)
            return

        logger.warning(
            "subscription_write_refused", method=scope["method"], path=scope["path"]
        )
        error = SubscriptionReadOnlyError()
        response = JSONResponse(
            status_code=403,
            content=build_error_response(
                error_code=error.error_code,
                message=error.message,
                request_id=scope.get("state", {}).get("request_id", ""),
            ),
        )
        await response(scope, receive, send)


@functools.cache
def subscription_access() -> CachedSubscriptionAccess:
    """One per process: the guard's (`main.py`)"""
    from config import config
    from src.shared.infra.database import app_session_maker

    return CachedSubscriptionAccess(
        app_session_maker, ttl_seconds=config.SUBSCRIPTION_STATUS_CACHE_SECONDS
    )
