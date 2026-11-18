"""One dataset for the whole isolation suite: tenant A, a snapshot of what A's
listings show, then tenant B with the same graph and a snapshot of B's rows."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from main import app
from src.integrations.infra.access import integration_access
from tests.integration.postgres.api import Api
from tests.integration.postgres.isolation.dataset import build_tenant
from tests.integration.postgres.isolation.harness import (
    MARKER_A,
    MARKER_B,
    Tenant,
    World,
    tenant_rows,
)
from tests.integration.postgres.isolation.routes import ROUTES, keys
from tests.integration.postgres.public_api import rate_limit_middleware
from tests.integration.postgres.support import (
    issue_headers,
    restore_event_bus,
    truncate_all,
)
from tests.integration.postgres.tenants import OTHER_TENANT_RUC, ensure_tenant


@pytest.fixture(autouse=True)
def _clean_state() -> Iterator[None]:
    """The package shares one dataset: only restore the event handlers"""
    restore_event_bus()
    yield


@pytest.fixture(scope="package")
def world(pg_engine: Engine) -> Iterator[World]:
    truncate_all(pg_engine)
    restore_event_bus()
    client = TestClient(app)
    # The suite calls the public API many times in a row: no rate limits, and
    # no usage counted (B's calls would change B's rows)
    limits = rate_limit_middleware(client)
    limiter, limits.limiter = limits.limiter, None
    access = integration_access()
    access.record_request = lambda *args, **kwargs: None  # ty: ignore[invalid-assignment]

    a_id = ensure_tenant(pg_engine)
    a = Tenant(
        a_id,
        Api(client, issue_headers(pg_engine, tenant_id=a_id, username="admin-a")),
        {},
    )
    a.ids.update(build_tenant(a.api, MARKER_A, 1, a_id))
    a.integration = a.ids.pop("api_headers")
    listings = {
        key: a.call(key, ROUTES[key], a.ids, query=False) for key in keys("listing")
    }

    b_id = ensure_tenant(pg_engine, OTHER_TENANT_RUC)
    b = Tenant(
        b_id,
        Api(client, issue_headers(pg_engine, tenant_id=b_id, username="admin-b")),
        {},
    )
    b.ids.update(build_tenant(b.api, MARKER_B, 2, b_id))
    b.integration = b.ids.pop("api_headers")
    yield World(a, b, listings, tenant_rows(pg_engine, b_id))
    limits.limiter = limiter
    del access.record_request
