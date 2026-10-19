"""One dataset for the whole isolation suite: tenant A, a snapshot of what A's
listings show, then tenant B with the same graph and a snapshot of B's rows."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from main import app
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
def world(pg_engine: Engine) -> World:
    truncate_all(pg_engine)
    restore_event_bus()
    client = TestClient(app)

    a_id = ensure_tenant(pg_engine)
    a = Tenant(
        a_id,
        Api(client, issue_headers(pg_engine, tenant_id=a_id, username="admin-a")),
        {},
    )
    a.ids.update(build_tenant(a.api, MARKER_A, 1))
    listings = {
        key: a.call(key, ROUTES[key], a.ids, query=False) for key in keys("listing")
    }

    b_id = ensure_tenant(pg_engine, OTHER_TENANT_RUC)
    b = Tenant(
        b_id,
        Api(client, issue_headers(pg_engine, tenant_id=b_id, username="admin-b")),
        {},
    )
    b.ids.update(build_tenant(b.api, MARKER_B, 2))
    return World(a, b, listings, tenant_rows(pg_engine, b_id))
