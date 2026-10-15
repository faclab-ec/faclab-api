import json

from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.trace import SpanContext, SpanKind, StatusCode

from src.shared.infra.kafka.consumer import KafkaMessageConsumer


def _consumer(handler) -> KafkaMessageConsumer:
    return KafkaMessageConsumer("localhost:9092", "test", {"invoices": handler})


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
