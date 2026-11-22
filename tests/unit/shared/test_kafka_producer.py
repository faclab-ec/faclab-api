import pytest
from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.trace import SpanKind

from tests.kafka import FakeBroker, fake_producer


@pytest.fixture
def producer():
    """Producer whose event loop runs in a thread, as after start(), with a
    fake broker instead of Kafka."""
    with fake_producer() as (producer, _broker):
        yield producer


def _outbox_headers() -> tuple[list[tuple[str, bytes]], trace.SpanContext]:
    """What OutboxWriter stores: the context of the request that wrote it."""
    with trace.get_tracer("api").start_as_current_span("event.handle") as span:
        carrier: dict[str, str] = {}
        inject(carrier)
    return [(k, v.encode()) for k, v in carrier.items()], span.get_span_context()


def test_sending_continues_the_trace_of_the_request(producer, span_exporter):
    headers, written_by = _outbox_headers()

    producer.publish("sales.confirmed", {"event_id": "e-1"}, headers, key="tenant-1")

    send = next(
        s
        for s in span_exporter.get_finished_spans()
        if s.name == "send sales.confirmed"
    )
    assert send.kind == SpanKind.PRODUCER
    assert send.context.trace_id == written_by.trace_id
    assert send.parent is not None
    assert send.parent.span_id == written_by.span_id
    assert send.attributes is not None
    assert send.attributes["messaging.destination.name"] == "sales.confirmed"
    assert send.attributes["messaging.message.id"] == "e-1"
    assert send.attributes["messaging.system"] == "kafka"
    # The partition key: the tenant, so its messages keep their order
    assert send.attributes["messaging.kafka.message.key"] == "tenant-1"


def test_a_message_without_key_has_no_key_attribute(producer, span_exporter):
    producer.publish("sales.confirmed", {"event_id": "e-1"}, [])

    (send,) = span_exporter.get_finished_spans()
    assert send.attributes is not None
    assert "messaging.kafka.message.key" not in send.attributes


def test_the_consumer_receives_the_send_span_as_parent(producer, span_exporter):
    headers, _ = _outbox_headers()

    producer.publish("sales.confirmed", {"event_id": "e-1"}, headers)

    send = next(
        s
        for s in span_exporter.get_finished_spans()
        if s.name == "send sales.confirmed"
    )
    (_, _, sent_headers) = producer._producer.sent[0]
    traceparent = dict(sent_headers)["traceparent"].decode()
    assert traceparent.split("-")[1] == format(send.context.trace_id, "032x")
    assert traceparent.split("-")[2] == format(send.context.span_id, "016x")


def test_the_key_goes_to_the_broker_as_bytes(producer):
    producer.publish("sales.confirmed", {"event_id": "e-1"}, [], key="tenant-1")
    producer.publish("sales.confirmed", {"event_id": "e-2"}, [])

    assert producer._producer.keys == [b"tenant-1", None]


class BrokenBroker(FakeBroker):
    async def send_and_wait(self, topic, value, key=None, headers=None):
        raise ValueError("message too large")


def test_each_send_is_counted_by_topic(producer, recorded_metrics):
    producer.publish("sales.confirmed", {"event_id": "e-1"}, [])

    assert recorded_metrics.collect().points("messaging.client.sent.messages") == [
        (
            1,
            {
                "messaging.system": "kafka",
                "messaging.operation.name": "send",
                "messaging.destination.name": "sales.confirmed",
            },
        )
    ]


def test_a_failed_send_carries_its_error_type(producer, recorded_metrics):
    producer._producer = BrokenBroker()

    with pytest.raises(ValueError):
        producer.publish("sales.confirmed", {"event_id": "e-1"}, [])

    ((value, attributes),) = recorded_metrics.collect().points(
        "messaging.client.sent.messages"
    )
    assert value == 1
    assert attributes["error.type"] == "ValueError"
    assert attributes["messaging.destination.name"] == "sales.confirmed"
