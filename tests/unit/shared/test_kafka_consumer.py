import json

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
