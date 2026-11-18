"""Rate limits of the public API on PostgreSQL (S6.3, D-6): the counters are
shared rows, a client over its limit gets 429 with Retry-After, and its tenant's
limit binds every client of it."""

import pytest
from sqlalchemy import select

from src.public_api.app.rate_limit import RateLimit
from src.public_api.infra.models import ApiRateLimitModel
from tests.integration.postgres.api import Api
from tests.integration.postgres.public_api import (
    assert_documented,
    integration_headers,
    rate_limit_middleware,
)


@pytest.fixture
def limits(client, monkeypatch):
    middleware = rate_limit_middleware(client)

    def set_limits(client_limit: RateLimit, tenant_limit: RateLimit) -> None:
        monkeypatch.setattr(middleware, "client_limit", client_limit)
        monkeypatch.setattr(middleware, "tenant_limit", tenant_limit)

    return set_limits


@pytest.fixture
def api(client, admin) -> Api:
    return Api(client, admin)


def test_over_its_limit_a_client_waits(client, api, limits, db_session):
    limits(RateLimit(per_minute=60, burst=2), RateLimit(per_minute=600, burst=50))
    headers = integration_headers(api, client)

    first = client.get("/api/v1/products", headers=headers)
    second = client.get("/api/v1/products", headers=headers)
    third = client.get("/api/v1/products", headers=headers)

    assert first.status_code == second.status_code == 200
    assert (first.headers["RateLimit-Limit"], first.headers["RateLimit-Remaining"]) == (
        "2",
        "1",
    )
    assert first.headers["RateLimit-Policy"] == "2;w=2"
    assert second.headers["RateLimit-Remaining"] == "0"
    assert third.status_code == 429
    assert third.headers["Retry-After"] == "1"
    assert_documented(third)
    assert third.json()["errors"][0]["code"] == "RATE_LIMITED"
    # One row per key: the client's and its tenant's
    keys = db_session.scalars(select(ApiRateLimitModel.key)).all()
    assert sorted(key.split(":")[0] for key in keys) == ["client", "tenant"]


def test_the_tenants_limit_binds_all_its_clients(client, api, limits):
    limits(RateLimit(per_minute=600, burst=50), RateLimit(per_minute=60, burst=2))
    shop = integration_headers(api, client, name="Tienda web")
    erp = integration_headers(api, client, name="ERP")

    assert client.get("/api/v1/products", headers=shop).status_code == 200
    assert client.get("/api/v1/products", headers=erp).status_code == 200
    refused = client.get("/api/v1/products", headers=shop)

    assert refused.status_code == 429
    assert refused.headers["RateLimit-Limit"] == "2"


def test_the_rest_of_the_api_isnt_limited(client, api, admin, limits):
    limits(RateLimit(per_minute=60, burst=1), RateLimit(per_minute=60, burst=1))
    headers = integration_headers(api, client)
    client.get("/api/v1/products", headers=headers)

    # A user on the internal API, and the token endpoint, go on
    for _ in range(3):
        assert client.get("/api/admin/products", headers=admin).status_code == 200
    assert (
        "RateLimit-Limit"
        not in client.get("/api/admin/products", headers=admin).headers
    )
