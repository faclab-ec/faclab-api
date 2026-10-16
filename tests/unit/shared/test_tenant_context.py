"""The tenant context: how it is set, where it is seen and where it is not."""

import threading
from uuid import UUID

import pytest
import structlog
from opentelemetry import trace
from wireup import create_async_container

import src
from src.shared.domain.tenant import (
    TenantContext,
    TenantContextRequiredError,
    TenantSource,
    current_tenant,
    current_tenant_id,
    require_tenant,
    use_tenant,
)
from src.shared.infra.events.scope import create_sync_scope
from src.shared.infra.tenant import tenant_context, tenant_scope

TENANT_A = TenantContext(
    UUID("00000000-0000-4000-8000-0000000000a1"), TenantSource.TASK
)
TENANT_B = TenantContext(
    UUID("00000000-0000-4000-8000-0000000000b2"), TenantSource.REQUEST, user_id=7
)

logger = structlog.get_logger("tests.tenant")


def test_there_is_no_tenant_by_default():
    assert current_tenant() is None
    assert current_tenant_id() is None
    with pytest.raises(TenantContextRequiredError, match="listing requires"):
        require_tenant("listing")


def test_a_nested_context_restores_the_outer_one():
    with use_tenant(TENANT_A):
        with use_tenant(TENANT_B):
            assert require_tenant() == TENANT_B
        assert require_tenant() == TENANT_A
    assert current_tenant() is None


def test_the_context_is_immutable():
    with pytest.raises(AttributeError):
        TENANT_A.tenant_id = TENANT_B.tenant_id  # ty: ignore[invalid-assignment]


def test_a_new_thread_does_not_inherit_the_context():
    seen = []
    with use_tenant(TENANT_A):
        thread = threading.Thread(target=lambda: seen.append(current_tenant()))
        thread.start()
        thread.join()

    assert seen == [None]


def test_tenant_scope_reaches_logs_and_the_active_span(span_exporter, json_logs):
    tracer = trace.get_tracer("tests.tenant")
    with tracer.start_as_current_span("work"), tenant_scope(TENANT_A):
        logger.info("inside_tenant")
    logger.info("outside_tenant")

    lines = {line["event"]: line for line in json_logs()}
    assert lines["inside_tenant"]["faclab.tenant.id"] == str(TENANT_A.tenant_id)
    assert "faclab.tenant.id" not in lines["outside_tenant"]
    (span,) = span_exporter.get_finished_spans()
    assert span.attributes is not None
    assert span.attributes["faclab.tenant.id"] == str(TENANT_A.tenant_id)


@pytest.fixture
def container(monkeypatch):
    container = create_async_container(injectables=[tenant_context])
    monkeypatch.setattr(src, "wireup_container", container)
    return container


def test_a_task_scope_runs_in_the_tenant_it_is_given(container):
    with create_sync_scope(tenant=TENANT_A) as scope:
        assert scope.get(TenantContext) == TENANT_A
        assert current_tenant() == TENANT_A
    assert current_tenant() is None


def test_a_scope_inherits_the_current_tenant(container):
    with use_tenant(TENANT_B), create_sync_scope() as scope:
        assert scope.get(TenantContext) == TENANT_B


def test_injecting_the_tenant_without_a_context_fails(container):
    with create_sync_scope() as scope, pytest.raises(TenantContextRequiredError):
        scope.get(TenantContext)
