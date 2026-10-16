"""Test-wide settings, applied before any test module imports `config`."""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest

from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant

# Tests never export telemetry nor talk to Kafka.
os.environ["OTEL_ENABLED"] = "false"
os.environ["KAFKA_ENABLED"] = "false"

# Postgres-backed tests run against TEST_DATABASE_URL. Point the app at it too,
# so routes exercised through TestClient hit the same database.
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

_POSTGRES_TESTS = Path(__file__).parent / "integration" / "postgres"

TEST_TENANT_ID = UUID("00000000-0000-4000-8000-00000000000a")


@pytest.fixture
def in_tenant() -> Iterator[TenantContext]:
    """Runs the test inside a tenant context, as a request does."""
    with use_tenant(TenantContext(TEST_TENANT_ID, TenantSource.TASK)) as context:
        yield context


def pytest_collection_modifyitems(config, items):
    """Mark tests under integration/postgres and skip them without a database."""
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if _POSTGRES_TESTS in Path(item.path).parents:
            item.add_marker(pytest.mark.postgres)
            if not os.environ.get("TEST_DATABASE_URL"):
                item.add_marker(skip)
