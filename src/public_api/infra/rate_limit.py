"""The rate limits of the public API in PostgreSQL (S6.3, D-6) and the
middleware that applies them.

Each check is one statement per key: an upsert that moves the key's TAT only
when the request fits (`INSERT … ON CONFLICT … DO UPDATE … WHERE … RETURNING`),
atomic and shared by every process. It runs in a short transaction of its own,
before the route and apart from its unit of work. If the store fails, the
request goes on (the limit protects the service, it never takes it down).
"""

import time
from collections.abc import Callable, Sequence
from typing import cast

import structlog
from sqlalchemy import Table, delete, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.auth.domain.principals import IntegrationPrincipal
from src.public_api.app.rate_limit import (
    Decision,
    RateLimit,
    RateLimiter,
    admit,
    binding,
)
from src.public_api.infra.models import ApiRateLimitModel
from src.shared.infra.middlewares import build_error_response

logger = structlog.get_logger(__name__)

PUBLIC_API_PREFIX = "/api/v1"


class PgRateLimiter(RateLimiter):
    def __init__(
        self,
        session_maker: Callable[[], sessionmaker[Session]],
        clock: Callable[[], float] = time.time,
    ):
        # A factory: the engine is created on the first request that needs it
        self._session_maker = session_maker
        self._clock = clock

    def check(self, keys: Sequence[tuple[str, RateLimit]]) -> Decision:
        decisions = []
        with self._session_maker()() as session, session.begin():
            for key, limit in keys:
                decision = self._count(session, key, limit, self._clock())
                decisions.append(decision)
                if not decision.allowed:
                    break
        return binding(decisions)

    def _count(
        self, session: Session, key: str, limit: RateLimit, now: float
    ) -> Decision:
        table = cast(Table, ApiRateLimitModel.__table__)
        dialect = session.get_bind().dialect.name
        insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
        greatest = func.greatest if dialect == "postgresql" else func.max
        current = greatest(table.c.tat, now)
        statement = (
            insert(table)
            .values(key=key, tat=now + limit.interval)
            .on_conflict_do_update(
                index_elements=[table.c.key],
                set_={"tat": current + limit.interval},
                where=current + limit.interval - now <= limit.capacity + 1e-9,
            )
            .returning(table.c.tat)
        )
        moved = session.execute(statement).scalar()
        if moved is not None:
            decision, _ = admit(limit, moved - limit.interval, now)
            return decision
        tat = session.scalar(select(table.c.tat).where(table.c.key == key))
        decision, _ = admit(limit, tat, now)
        return decision


def purge_expired(session_maker: sessionmaker[Session], now: float) -> int:
    """Deletes the keys whose bucket is full again: they say nothing more than
    no row"""
    with session_maker() as session, session.begin():
        result = session.execute(
            delete(ApiRateLimitModel)
            .where(ApiRateLimitModel.tat < now)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount


def purge() -> int:
    """The worker's task, as faclab_worker"""
    from src.shared.infra.database import worker_session_maker

    deleted = purge_expired(worker_session_maker(), time.time())
    logger.info("api_rate_limits_purged", deleted=deleted)
    return deleted


class PublicApiRateLimitMiddleware:
    """Counts each request of an integration client to `/api/v1` against its
    client's limit and its tenant's. It runs inside `AuthMiddleware` (it needs
    the client) and outside the error handler. A refused request gets 429
    `RATE_LIMITED` with `Retry-After`; every counted one, the `RateLimit-*`
    headers of the key closest to its limit."""

    def __init__(
        self,
        app: ASGIApp,
        limiter: RateLimiter | None,
        client_limit: RateLimit,
        tenant_limit: RateLimit,
    ):
        self.app = app
        self.limiter = limiter
        self.client_limit = client_limit
        self.tenant_limit = tenant_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        client = self._client(scope)
        if client is None or self.limiter is None:
            await self.app(scope, receive, send)
            return
        keys = [
            (f"client:{client.tenant_id}:{client.client_id}", self.client_limit),
            (f"tenant:{client.tenant_id}", self.tenant_limit),
        ]
        try:
            decision = await run_in_threadpool(self.limiter.check, keys)
        except Exception:
            logger.exception("rate_limit_check_failed", client_id=client.public_id)
            await self.app(scope, receive, send)
            return

        headers = rate_limit_headers(decision)
        if not decision.allowed:
            logger.info(
                "public_api_rate_limited",
                client_id=client.public_id,
                retry_after=decision.retry_after,
            )
            request_id = scope.get("state", {}).get("request_id", "")
            body = build_error_response(
                error_code="RATE_LIMITED",
                message=(f"Too many requests: retry in {decision.retry_after} seconds"),
                request_id=request_id,
            )
            response = JSONResponse(
                status_code=429,
                content=body,
                headers={**headers, "Retry-After": str(decision.retry_after)},
            )
            await response(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name, value in headers.items():
                    response_headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)

    @staticmethod
    def _client(scope: Scope) -> IntegrationPrincipal | None:
        if scope["type"] != "http" or not scope["path"].startswith(PUBLIC_API_PREFIX):
            return None
        integration = scope.get("state", {}).get("integration")
        return integration if isinstance(integration, IntegrationPrincipal) else None


def rate_limit_headers(decision: Decision) -> dict[str, str]:
    return {
        "RateLimit-Limit": str(decision.limit.burst),
        "RateLimit-Remaining": str(decision.remaining),
        "RateLimit-Reset": str(decision.reset),
        "RateLimit-Policy": decision.limit.policy,
    }
