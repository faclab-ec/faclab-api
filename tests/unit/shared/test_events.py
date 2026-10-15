from dataclasses import dataclass
from typing import Any

import pytest

from src.shared.domain.events import DomainEvent
from src.shared.infra.events.event_bus import EventBus


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
    assert "event_id" in d
    assert "occurred_at" in d


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
