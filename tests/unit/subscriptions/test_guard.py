"""Read-only mode of a tenant whose subscription isn't active (S8.4)."""

from datetime import datetime, timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send

from main import app as main_app
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.subscriptions.domain.entities import SubscriptionStatus
from src.subscriptions.infra.guard import (
    GUARDED_PREFIXES,
    WRITE_ALLOWED,
    CachedSubscriptionAccess,
    SubscriptionGuardMiddleware,
    is_guarded,
)
from src.subscriptions.infra.models import PlanModel, SubscriptionModel
from tests.conftest import TEST_TENANT_ID
from tests.sqlite import sqlite_session

NOW = datetime(2026, 11, 24, 10, 0)


def _routes() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in main_app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


@pytest.mark.parametrize(("method", "path"), WRITE_ALLOWED)
def test_every_allowed_write_is_a_route_of_the_api(method, path):
    assert (method, path) in _routes()


def test_every_write_of_the_api_is_refused_unless_allowed():
    allowed = set(WRITE_ALLOWED)
    writes = {
        (method, path)
        for method, path in _routes()
        if method not in {"GET", "HEAD"} and path.startswith(GUARDED_PREFIXES)
    }

    assert writes > allowed
    for method, path in writes:
        concrete = path.replace("{", "").replace("}", "")
        assert is_guarded(method, concrete) is ((method, path) not in allowed)


@pytest.mark.parametrize(
    ("method", "path", "guarded"),
    [
        ("GET", "/api/pos/sales", False),
        ("HEAD", "/api/admin/products", False),
        ("OPTIONS", "/api/pos/sales/quick", False),
        ("POST", "/api/pos/sales/quick", True),
        ("POST", "/api/v1/sales", True),
        ("PUT", "/api/admin/products/7", True),
        ("DELETE", "/api/admin/branches/2", True),
        ("POST", "/api/pos/prices/resolve", False),
        ("POST", "/api/pos/shifts/12/close", False),
        ("POST", "/api/pos/shifts/open", True),
        ("POST", "/api/admin/sales/5/request-invoice", False),
        ("POST", "/api/admin/sales/5/request-invoice/", False),
        ("POST", "/api/admin/sales/5/request-invoice/x", True),
        ("PUT", "/api/admin/webhook-endpoints/3", True),
        ("DELETE", "/api/admin/webhook-endpoints/3", False),
        ("POST", "/api/admin/users/9/deactivate", False),
        ("POST", "/api/admin/users/9/activate", True),
        # Logging in, refreshing and the OAuth token always work
        ("POST", "/api/auth/login", False),
        ("POST", "/api/auth/refresh", False),
        ("POST", "/api/auth/change-password", False),
        ("POST", "/api/oauth/token", False),
    ],
)
def test_a_read_only_tenant_is_refused_only_writes(method, path, guarded):
    assert is_guarded(method, path) is guarded


class FixedAccess(CachedSubscriptionAccess):
    def __init__(self, writes: bool | Exception):
        self.writes = writes
        self.asked: list[UUID] = []

    def allows_writes(self, tenant_id: UUID) -> bool:
        self.asked.append(tenant_id)
        if isinstance(self.writes, Exception):
            raise self.writes
        return self.writes


class InTenant:
    """What AuthMiddleware does: runs the request in its token's tenant"""

    def __init__(self, app: ASGIApp, tenant: TenantContext | None):
        self.app = app
        self.tenant = tenant

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope.setdefault("state", {})["request_id"] = "req-1"
        if self.tenant is None:
            await self.app(scope, receive, send)
            return
        with use_tenant(self.tenant):
            await self.app(scope, receive, send)


def _client(access, tenant=TenantContext(TEST_TENANT_ID, TenantSource.REQUEST)):
    app = FastAPI()

    @app.get("/api/pos/sales")
    def sales():
        return {"data": []}

    @app.post("/api/pos/sales/quick")
    def quick_sale():
        return {"data": {"id": 1}}

    @app.post("/api/pos/shifts/{shift_id}/close")
    def close_shift(shift_id: int):
        return {"data": {"id": shift_id}}

    app.add_middleware(SubscriptionGuardMiddleware, access=access)
    app.add_middleware(InTenant, tenant=tenant)
    return TestClient(app)


def test_a_read_only_tenant_reads_but_doesnt_sell():
    access = FixedAccess(writes=False)
    client = _client(access)

    read = client.get("/api/pos/sales")
    sale = client.post("/api/pos/sales/quick")
    close = client.post("/api/pos/shifts/3/close")

    assert (read.status_code, close.status_code) == (200, 200)
    assert sale.status_code == 403
    assert sale.json()["errors"][0]["code"] == "SUBSCRIPTION_READ_ONLY"
    assert sale.json()["meta"]["requestId"] == "req-1"
    # Only the guarded write asked for the subscription
    assert access.asked == [TEST_TENANT_ID]


def test_an_active_tenant_writes():
    assert (
        _client(FixedAccess(writes=True)).post("/api/pos/sales/quick").status_code
        == 200
    )


def test_a_request_without_a_tenant_goes_on_to_its_route():
    access = FixedAccess(writes=False)

    response = _client(access, tenant=None).post("/api/pos/sales/quick")

    assert response.status_code == 200
    assert access.asked == []


def test_the_rollback_switch_lets_every_write_through():
    assert _client(None).post("/api/pos/sales/quick").status_code == 200


def test_a_failing_check_lets_the_request_through():
    client = _client(FixedAccess(writes=RuntimeError("database down")))

    assert client.post("/api/pos/sales/quick").status_code == 200


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def session_maker(in_tenant):
    session = sqlite_session([PlanModel, SubscriptionModel])
    session.add(PlanModel(id=1, code="basico", name="Básico"))
    session.commit()
    factory = sessionmaker(bind=session.get_bind())
    yield lambda: factory
    session.close()


def _subscribe(factory, status: SubscriptionStatus, trial_ends_at=None) -> None:
    with factory()() as session:
        session.query(SubscriptionModel).delete()
        session.add(
            SubscriptionModel(
                tenant_id=TEST_TENANT_ID,
                plan_id=1,
                status=status.value,
                trial_ends_at=trial_ends_at,
            )
        )
        session.commit()


def test_the_status_is_cached_for_its_ttl(session_maker):
    clock = Clock()
    access = CachedSubscriptionAccess(
        session_maker, ttl_seconds=30, clock=clock, now=lambda: NOW
    )
    _subscribe(session_maker, SubscriptionStatus.ACTIVE)
    assert access.allows_writes(TEST_TENANT_ID) is True

    _subscribe(session_maker, SubscriptionStatus.SUSPENDED)
    clock.now = 29
    assert access.allows_writes(TEST_TENANT_ID) is True
    clock.now = 31
    assert access.allows_writes(TEST_TENANT_ID) is False


def test_a_trial_stops_writing_when_it_ends(session_maker):
    moments = iter([NOW, NOW + timedelta(days=2)])
    access = CachedSubscriptionAccess(
        session_maker, ttl_seconds=30, clock=Clock(), now=lambda: next(moments)
    )
    _subscribe(session_maker, SubscriptionStatus.TRIAL, NOW + timedelta(days=1))

    # Within the cache too: the end of the trial is checked on each request
    assert access.allows_writes(TEST_TENANT_ID) is True
    assert access.allows_writes(TEST_TENANT_ID) is False


def test_a_tenant_without_a_subscription_writes(session_maker):
    access = CachedSubscriptionAccess(session_maker, ttl_seconds=0)

    assert access.allows_writes(TEST_TENANT_ID) is True
