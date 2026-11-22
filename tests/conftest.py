"""Test-wide settings, applied before any test module imports `config`."""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant

if TYPE_CHECKING:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from tests.metrics import RecordedMetrics
    from tests.telemetry import JsonLogs

# Tests never export telemetry nor talk to Kafka.
os.environ["OTEL_ENABLED"] = "false"
os.environ["KAFKA_ENABLED"] = "false"

# Postgres-backed tests run against TEST_DATABASE_URL, a superuser that creates
# the database and looks at it from outside row-level security. The app, the
# worker and the migrations use their own roles on that database, as deployed
# (S2.4), so routes exercised through TestClient run as faclab_app.
_ROLE_URLS = {
    "DATABASE_URL": "TEST_DATABASE_URL_APP",
    "DATABASE_URL_WORKER": "TEST_DATABASE_URL_WORKER",
    "DATABASE_URL_MIGRATIONS": "TEST_DATABASE_URL_MIGRATIONS",
}
if os.environ.get("TEST_DATABASE_URL"):
    for target, source in _ROLE_URLS.items():
        if os.environ.get(source):
            os.environ[target] = os.environ[source]

_POSTGRES_TESTS = Path(__file__).parent / "integration" / "postgres"

TEST_TENANT_ID = UUID("00000000-0000-4000-8000-00000000000a")


@pytest.fixture
def recorded_metrics() -> "RecordedMetrics":
    """The metrics recorded from here on: call `.collect()` to read them (S7.1)."""
    from tests.metrics import RecordedMetrics, install_reader

    recorded = RecordedMetrics(install_reader())
    recorded.collect()  # what earlier tests left
    return recorded


@pytest.fixture
def span_exporter() -> "Iterator[InMemorySpanExporter]":
    """Spans finished during the test, kept in memory (`tests/telemetry.py`
    has the helpers to read them)."""
    from tests.telemetry import install_tracer_provider

    exporter = install_tracer_provider()
    exporter.clear()
    yield exporter
    exporter.clear()


@pytest.fixture
def json_logs() -> "Iterator[JsonLogs]":
    """Logs as the deployed API writes them (JSON lines); call the fixture to
    read the lines written so far."""
    from tests.telemetry import json_logs

    with json_logs() as logs:
        yield logs


@pytest.fixture
def in_tenant() -> Iterator[TenantContext]:
    """Runs the test inside a tenant context, as a request does."""
    with use_tenant(TenantContext(TEST_TENANT_ID, TenantSource.TASK)) as context:
        yield context


def pytest_configure(config):
    """With a database, the role URLs are required: without them the app would
    run as the superuser and row-level security would test nothing."""
    if not os.environ.get("TEST_DATABASE_URL"):
        return
    missing = [name for name in _ROLE_URLS.values() if not os.environ.get(name)]
    if missing:
        raise pytest.UsageError(
            f"TEST_DATABASE_URL is set but {', '.join(missing)} is not: the "
            "PostgreSQL tests need one URL per database role (see the Makefile's "
            "test-integration target)"
        )


def pytest_collection_modifyitems(config, items):
    """Mark tests under integration/postgres and skip them without a database."""
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if _POSTGRES_TESTS in Path(item.path).parents:
            item.add_marker(pytest.mark.postgres)
            if not os.environ.get("TEST_DATABASE_URL"):
                item.add_marker(skip)
