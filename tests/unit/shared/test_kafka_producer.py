import asyncio
import threading

import pytest
from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.trace import SpanKind

from src.shared.infra.kafka.producer import KafkaEventProducer


class FakeBroker:
    def __init__(self):
        self.sent: list[tuple[str, dict, list[tuple[str, bytes]]]] = []
        self.keys: list[bytes | None] = []

    async def send_and_wait(self, topic, value, key=None, headers=None):
        self.sent.append((topic, value, headers or []))
        self.keys.append(key)


@pytest.fixture
def producer():
    """Producer whose event loop runs in a thread, as after start(), with a
    fake broker instead of Kafka."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    producer = KafkaEventProducer("localhost:9092")
    producer._loop = loop
    producer._producer = FakeBroker()  # ty: ignore[invalid-assignment]
    yield producer
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


def _outbox_headers() -> tuple[list[tuple[str, bytes]], trace.SpanContext]:
    """What OutboxWriter stores: the context of the request that wrote it."""
    with trace.get_tracer("api").start_as_current_span("event.handle") as span:
        carrier: dict[str, str] = {}
        inject(carrier)
    return [(k, v.encode()) for k, v in carrier.items()], span.get_span_context()


def test_sending_continues_the_trace_of_the_request(producer, span_exporter):
    headers, written_by = _outbox_headers()

    producer.publish("sales.confirmed", {"event_id": "e-1"}, headers)

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
