from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest

from src.shared.domain.events import DomainEvent
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.shared.infra.events.event_bus import EventBus

TENANT_ID = UUID("00000000-0000-4000-8000-0000000000a1")
OTHER_TENANT_ID = UUID("00000000-0000-4000-8000-0000000000b2")


@dataclass
class OrderCreated(DomainEvent):
    order_total: float = 0.0

    def _payload(self) -> dict[str, Any]:
        return {"order_total": self.order_total}


@pytest.fixture(autouse=True)
def clear_event_bus():
    EventBus.clear()
    yield
    EventBus.clear()


def test_subscribe_and_publish():
    results = []

    def handler(event: OrderCreated):
        results.append(event.order_total)

    EventBus.subscribe(OrderCreated, handler)
    EventBus.publish(OrderCreated(aggregate_id=1, order_total=100.0))

    assert results == [100.0]


def test_publish_without_subscribers():
    EventBus.publish(OrderCreated(aggregate_id=1, order_total=50.0))


def test_handler_error_propagates_to_caller():
    """Event handler errors must propagate so the caller can rollback."""

    def failing_handler(event: OrderCreated):
        raise RuntimeError("handler failed")

    EventBus.subscribe(OrderCreated, failing_handler)

    with pytest.raises(RuntimeError, match="handler failed"):
        EventBus.publish(OrderCreated(aggregate_id=1, order_total=75.0))


def test_clear_removes_all():
    results = []

    def handler(event: OrderCreated):
        results.append(event.order_total)

    EventBus.subscribe(OrderCreated, handler)
    EventBus.clear()
    EventBus.publish(OrderCreated(aggregate_id=1, order_total=25.0))

    assert results == []


def test_event_to_dict():
    event = OrderCreated(aggregate_id=42, order_total=99.99)
    d = event.to_dict()

    assert d["event_type"] == "OrderCreated"
    assert d["aggregate_id"] == 42
    assert d["payload"] == {"order_total": 99.99}
    assert d["tenant_id"] is None
    assert "event_id" in d
    assert "occurred_at" in d


def test_an_event_belongs_to_the_tenant_it_was_raised_in():
    with use_tenant(TenantContext(TENANT_ID, TenantSource.REQUEST)):
        event = OrderCreated(aggregate_id=42)

    assert event.tenant_id == TENANT_ID
    assert event.to_dict()["tenant_id"] == str(TENANT_ID)
    assert OrderCreated(aggregate_id=43).tenant_id is None


def test_a_platform_task_can_name_the_tenant_of_an_event():
    event = OrderCreated(aggregate_id=42, tenant_id=OTHER_TENANT_ID)

    assert event.tenant_id == OTHER_TENANT_ID


def test_handlers_receive_the_event_with_its_tenant():
    received = []
    EventBus.subscribe(OrderCreated, lambda event: received.append(event.tenant_id))

    with use_tenant(TenantContext(TENANT_ID, TenantSource.REQUEST)):
        EventBus.publish(OrderCreated(aggregate_id=1))

    assert received == [TENANT_ID]


def test_a_domain_error_in_a_handler_does_not_fail_its_span(span_exporter):
    from opentelemetry.trace import StatusCode

    from src.shared.domain.exceptions import ValidationError

    def rejecting_handler(event: OrderCreated):
        raise ValidationError("not enough stock")

    EventBus.subscribe(OrderCreated, rejecting_handler)

    with pytest.raises(ValidationError):
        EventBus.publish(OrderCreated(aggregate_id=1, order_total=10.0))

    spans = {span.name: span for span in span_exporter.get_finished_spans()}
    handle = spans["event.handle.rejecting_handler"]
    assert handle.status.status_code == StatusCode.UNSET
    assert handle.attributes is not None
    assert handle.attributes["faclab.error.code"] == "VALIDATION_ERROR"
    assert spans["event.publish.OrderCreated"].status.status_code == StatusCode.UNSET


def test_an_unexpected_error_in_a_handler_fails_its_span(span_exporter):
    from opentelemetry.trace import StatusCode

    def failing_handler(event: OrderCreated):
        raise RuntimeError("handler failed")

    EventBus.subscribe(OrderCreated, failing_handler)

    with pytest.raises(RuntimeError):
        EventBus.publish(OrderCreated(aggregate_id=1, order_total=10.0))

    spans = {span.name: span for span in span_exporter.get_finished_spans()}
    assert spans["event.handle.failing_handler"].status.status_code == StatusCode.ERROR
