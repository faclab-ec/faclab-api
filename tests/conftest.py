"""Test-wide settings, applied before any test module imports `config`."""

import os
from pathlib import Path

import pytest

# Tests never export telemetry nor talk to Kafka.
os.environ["OTEL_ENABLED"] = "false"
os.environ["KAFKA_ENABLED"] = "false"

# Postgres-backed tests run against TEST_DATABASE_URL. Point the app at it too,
# so routes exercised through TestClient hit the same database.
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

_POSTGRES_TESTS = Path(__file__).parent / "integration" / "postgres"


def pytest_collection_modifyitems(config, items):
    """Mark tests under integration/postgres and skip them without a database."""
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if _POSTGRES_TESTS in Path(item.path).parents:
            item.add_marker(pytest.mark.postgres)
            if not os.environ.get("TEST_DATABASE_URL"):
                item.add_marker(skip)
