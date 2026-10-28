import asyncio
import json
from uuid import UUID

import pytest
from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.trace import SpanContext, SpanKind, StatusCode

from src.shared.domain.tenant import TenantSource, current_tenant
from src.shared.infra.kafka.consumer import KafkaMessageConsumer

TENANT_ID = "00000000-0000-4000-8000-0000000000a1"


def _consumer(handler, **kwargs) -> KafkaMessageConsumer:
    return KafkaMessageConsumer(
        "localhost:9092", "test", {"invoices": handler}, **kwargs
    )


class Sink:
    def __init__(self, broken: bool = False):
        self.letters = []
        self.broken = broken

    def record(self, letter):
        if self.broken:
            raise ConnectionError("database is down")
        self.letters.append(letter)


class FailsTimes:
    """Handler that fails its first `times` calls"""

    def __init__(self, times: int):
        self.times = times
        self.calls = 0
        self.received = []

    def __call__(self, message):
        self.calls += 1
        if self.calls <= self.times:
            raise ConnectionError(f"failure {self.calls}")
        self.received.append(message)


def _handle(consumer: KafkaMessageConsumer, value: bytes, headers=()) -> bool:
    return asyncio.run(
        consumer.handle(
            "invoices", value, list(headers), partition=2, offset=7, key=b"k-1"
        )
    )


def test_handled_message_can_be_committed():
    received = []
    consumer = _consumer(received.append)

    ok = consumer.process(
        "invoices", json.dumps({"saleId": "1"}).encode(), [("traceparent", b"x")]
    )

    assert ok is True
    assert received == [{"saleId": "1"}]


def test_failed_handler_asks_for_a_retry():
    def failing(_message):
        raise ConnectionError("database is down")

    assert _consumer(failing).process("invoices", b'{"saleId": "1"}') is False


def test_message_that_is_not_a_json_object_is_discarded():
    received = []
    consumer = _consumer(received.append)

    assert consumer.process("invoices", b"not json") is True
    assert consumer.process("invoices", b"[1, 2]") is True
    assert consumer.process("invoices", None) is True
    assert received == []


def _traceparent() -> tuple[list[tuple[str, bytes]], SpanContext]:
    """Headers of a message sent from inside a span of another service."""
    with trace.get_tracer("producer").start_as_current_span("send invoices") as span:
        carrier: dict[str, str] = {}
        inject(carrier)
    return [(k, v.encode()) for k, v in carrier.items()], span.get_span_context()


def test_processing_continues_the_trace_of_the_message(span_exporter):
    headers, sent_from = _traceparent()

    _consumer(lambda _message: None).process(
        "invoices", b'{"saleId": "1"}', headers, partition=0, offset=41
    )

    process = next(
        s for s in span_exporter.get_finished_spans() if s.name == "process invoices"
    )
    assert process.kind == SpanKind.CONSUMER
    assert process.context.trace_id == sent_from.trace_id
    assert process.parent is not None
    assert process.parent.span_id == sent_from.span_id
    assert process.attributes is not None
    assert process.attributes["messaging.system"] == "kafka"
    assert process.attributes["messaging.destination.name"] == "invoices"
    assert process.attributes["messaging.consumer.group.name"] == "test"
    assert process.attributes["messaging.kafka.offset"] == 41


def test_a_failed_message_fails_its_span(span_exporter):
    def failing(_message):
        raise ConnectionError("database is down")

    _consumer(failing).process("invoices", b'{"saleId": "1"}')

    (process,) = span_exporter.get_finished_spans()
    assert process.status.status_code == StatusCode.ERROR


def _tenant_seen(value: bytes, headers=()) -> list:
    """Process a message and return the tenant context its handler saw."""
    seen = []
    consumer = _consumer(lambda _message: seen.append(current_tenant()))
    assert consumer.process("invoices", value, list(headers)) is True
    return seen


def test_the_handler_runs_in_the_tenant_of_the_header(span_exporter):
    [context] = _tenant_seen(
        b'{"saleId": "1"}', [("faclab-tenant-id", TENANT_ID.encode())]
    )

    assert context is not None
    assert (str(context.tenant_id), context.source) == (TENANT_ID, TenantSource.MESSAGE)
    assert current_tenant() is None
    (process,) = span_exporter.get_finished_spans()
    assert process.attributes is not None
    assert process.attributes["faclab.tenant.id"] == TENANT_ID


def test_without_a_header_the_envelope_tenant_is_used():
    [context] = _tenant_seen(json.dumps({"tenant_id": TENANT_ID}).encode())

    assert context is not None
    assert str(context.tenant_id) == TENANT_ID


def test_a_message_without_a_tenant_runs_without_context():
    # faclab-invoicing doesn't send one yet in `invoices`
    assert _tenant_seen(b'{"saleId": "1"}') == [None]


def test_a_message_with_a_tenant_that_is_not_a_uuid_is_discarded():
    assert _tenant_seen(b'{"saleId": "1"}', [("faclab-tenant-id", b"acme")]) == []
    assert _tenant_seen(json.dumps({"tenant_id": 7}).encode()) == []


def test_a_failing_message_is_retried_until_it_works():
    handler = FailsTimes(2)
    sink = Sink()
    consumer = _consumer(handler, dead_letters=sink, retry_base_delay=0)

    assert _handle(consumer, b'{"saleId": "1"}') is True

    assert handler.calls == 3
    assert handler.received == [{"saleId": "1"}]
    assert sink.letters == []


def test_after_its_attempts_a_message_goes_to_the_dead_letters():
    handler = FailsTimes(10)
    sink = Sink()
    consumer = _consumer(handler, dead_letters=sink, max_attempts=3, retry_base_delay=0)
    headers = [("faclab-tenant-id", TENANT_ID.encode()), ("traceparent", b"00-x")]

    # Committed: the partition goes on with the next message
    assert _handle(consumer, b'{"saleId": "1"}', headers) is True

    assert handler.calls == 3
    [letter] = sink.letters
    assert (letter.topic, letter.partition, letter.offset, letter.key) == (
        "invoices",
        2,
        7,
        "k-1",
    )
    assert letter.consumer_group == "test"
    assert letter.tenant_id == UUID(TENANT_ID)
    assert letter.headers == {"faclab-tenant-id": TENANT_ID, "traceparent": "00-x"}
    assert letter.value == '{"saleId": "1"}'
    assert (letter.error, letter.attempts) == ("failure 3", 3)


def test_a_message_that_cant_be_kept_is_not_committed():
    consumer = _consumer(
        FailsTimes(10),
        dead_letters=Sink(broken=True),
        max_attempts=2,
        retry_base_delay=0,
    )

    assert _handle(consumer, b'{"saleId": "1"}') is False


def test_without_dead_letters_a_failing_message_is_not_committed():
    consumer = _consumer(FailsTimes(10), max_attempts=2, retry_base_delay=0)

    assert _handle(consumer, b'{"saleId": "1"}') is False


def test_dispatch_raises_what_the_handler_raises():
    def failing(_message):
        raise ConnectionError("database is down")

    with pytest.raises(ConnectionError, match="database is down"):
        _consumer(failing).dispatch("invoices", b'{"saleId": "1"}')
