"""Rate limits of the public API (S6.3, D-6): the GCRA, its store and the
middleware that answers 429."""

from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from src.auth.domain.principals import IntegrationPrincipal
from src.auth.domain.scopes import Scope
from src.public_api.app.rate_limit import (
    Decision,
    RateLimit,
    RateLimiter,
    admit,
    binding,
)
from src.public_api.infra.models import ApiRateLimitModel
from src.public_api.infra.rate_limit import (
    PgRateLimiter,
    PublicApiRateLimitMiddleware,
    purge_expired,
)
from tests.sqlite import sqlite_session

LIMIT = RateLimit(per_minute=600, burst=50)


def _burst(limit: RateLimit, requests: int, now: float = 1000.0) -> list[Decision]:
    tat, decisions = None, []
    for _ in range(requests):
        decision, tat = admit(limit, tat, now)
        decisions.append(decision)
    return decisions


def test_a_burst_takes_up_to_its_size_at_once():
    decisions = _burst(LIMIT, 51)

    assert all(d.allowed for d in decisions[:50])
    assert [d.remaining for d in decisions[:3]] == [49, 48, 47]
    assert decisions[49].remaining == 0
    assert not decisions[50].allowed
    # One request every 60/600 s comes back: retry in a second
    assert decisions[50].retry_after == 1


def test_the_bucket_refills_at_the_sustained_rate():
    tat = None
    for _ in range(50):
        _, tat = admit(LIMIT, tat, 1000.0)

    refused, _ = admit(LIMIT, tat, 1000.0)
    after_a_second, _ = admit(LIMIT, tat, 1001.0)
    much_later, _ = admit(LIMIT, tat, 2000.0)

    assert not refused.allowed
    assert after_a_second.allowed and after_a_second.remaining == 9
    assert much_later.remaining == 49


def test_the_policy_names_the_burst_and_its_window():
    assert LIMIT.policy == "50;w=5"
    assert RateLimit(per_minute=1200, burst=100).policy == "100;w=5"


def test_the_response_reports_the_key_closest_to_its_limit():
    roomy = _burst(RateLimit(1200, 100), 1)[0]
    tight = _burst(LIMIT, 40)[-1]
    refused = _burst(LIMIT, 51)[-1]

    assert binding([roomy, tight]) is tight
    assert binding([roomy, refused]) is refused


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def store():
    session = sqlite_session([ApiRateLimitModel])
    factory = sessionmaker(bind=session.get_bind())
    yield factory
    session.close()


def test_the_store_counts_each_key_apart(store):
    clock = _Clock()
    limiter = PgRateLimiter(lambda: store, clock=clock)
    small = RateLimit(per_minute=60, burst=2)

    first = limiter.check([("client:a", small), ("tenant:t", LIMIT)])
    second = limiter.check([("client:a", small), ("tenant:t", LIMIT)])
    third = limiter.check([("client:a", small), ("tenant:t", LIMIT)])
    other = limiter.check([("client:b", small), ("tenant:t", LIMIT)])

    assert (first.allowed, first.remaining) == (True, 1)
    assert (second.allowed, second.remaining) == (True, 0)
    assert (third.allowed, third.retry_after) == (False, 1)
    assert other.allowed
    clock.now += 1
    assert limiter.check([("client:a", small)]).allowed


def test_a_refused_client_doesnt_count_against_its_tenant(store):
    limiter = PgRateLimiter(lambda: store, clock=_Clock())
    one = RateLimit(per_minute=60, burst=1)
    tenant = RateLimit(per_minute=60, burst=3)

    limiter.check([("client:a", one), ("tenant:t", tenant)])
    limiter.check([("client:a", one), ("tenant:t", tenant)])

    left = limiter.check([("tenant:t", tenant)])
    assert left.remaining == 1


def test_the_purge_drops_the_full_buckets(store):
    limiter = PgRateLimiter(lambda: store, clock=_Clock())
    limiter.check([("client:a", LIMIT)])

    assert purge_expired(store, 1000.0) == 0
    assert purge_expired(store, 1001.0) == 1


class InMemoryRateLimiter(RateLimiter):
    """The same GCRA in a dict: the middleware's requests run in other threads,
    which an in-memory SQLite database doesn't reach"""

    def __init__(self, clock=None):
        self.clock = clock or _Clock()
        self.tats: dict[str, float] = {}

    def check(self, keys):
        decisions = []
        for key, limit in keys:
            decision, tat = admit(limit, self.tats.get(key), self.clock())
            self.tats[key] = tat
            decisions.append(decision)
            if not decision.allowed:
                break
        return binding(decisions)


def _client() -> IntegrationPrincipal:
    return IntegrationPrincipal(
        client_id=7,
        public_id="fl_test_0123456789ab",
        name="Tienda web",
        tenant_id=uuid4(),
        scopes=frozenset({Scope.PRODUCTS_READ}),
    )


def _app(limiter, integration: IntegrationPrincipal | None) -> TestClient:
    app = FastAPI()

    @app.get("/api/v1/products")
    def products():
        return {"data": []}

    @app.get("/api/admin/products")
    def internal():
        return {"data": []}

    app.add_middleware(
        PublicApiRateLimitMiddleware,
        limiter=limiter,
        client_limit=RateLimit(per_minute=60, burst=1),
        tenant_limit=LIMIT,
    )

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        request.state.integration = integration
        request.state.request_id = "req-1"
        return await call_next(request)

    return TestClient(app)


def test_over_the_limit_answers_429_with_retry_after():
    client = _app(InMemoryRateLimiter(), _client())

    first = client.get("/api/v1/products")
    second = client.get("/api/v1/products")

    assert first.status_code == 200
    assert first.headers["RateLimit-Limit"] == "1"
    assert first.headers["RateLimit-Remaining"] == "0"
    assert first.headers["RateLimit-Policy"] == "1;w=1"
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "1"
    assert second.json()["errors"][0]["code"] == "RATE_LIMITED"
    assert second.json()["meta"]["requestId"] == "req-1"


def test_only_integrations_on_the_public_api_are_counted():
    limiter = InMemoryRateLimiter()

    internal = _app(limiter, _client())
    user = _app(limiter, None)

    for _ in range(3):
        assert internal.get("/api/admin/products").status_code == 200
        assert user.get("/api/v1/products").status_code == 200
    assert "RateLimit-Limit" not in user.get("/api/v1/products").headers


def test_a_failing_store_lets_the_request_through():
    class Broken(RateLimiter):
        def check(self, keys):
            raise RuntimeError("database down")

    client = _app(Broken(), _client())

    assert client.get("/api/v1/products").status_code == 200
