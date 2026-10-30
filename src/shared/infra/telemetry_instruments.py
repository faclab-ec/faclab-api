from opentelemetry import metrics

_meter = metrics.get_meter("faclab-core", "1.0.0")

handler_duration = _meter.create_histogram(
    "handler.duration",
    unit="ms",
    description="Duration of handler execution in milliseconds",
)

handler_invocations = _meter.create_counter(
    "handler.invocations",
    description="Number of handler invocations",
)

handler_errors = _meter.create_counter(
    "handler.errors",
    description="Number of handler errors",
)

events_published = _meter.create_counter(
    "events.published",
    description="Number of domain events published",
)

event_handler_errors = _meter.create_counter(
    "events.handler_errors",
    description="Number of event handler errors",
)

kafka_messages_sent = _meter.create_counter(
    "kafka.messages_sent",
    description="Number of messages sent to Kafka",
)

kafka_send_errors = _meter.create_counter(
    "kafka.send_errors",
    description="Number of Kafka send failures",
)

kafka_messages_consumed = _meter.create_counter(
    "kafka.messages_consumed",
    description="Number of Kafka messages handled",
)

kafka_consume_errors = _meter.create_counter(
    "kafka.consume_errors",
    description="Number of Kafka messages whose handler failed (retried)",
)

reconciliation_discrepancies = _meter.create_gauge(
    "faclab.reconciliation.discrepancies",
    description="Open invoice discrepancies of every tenant, by kind (S4.3)",
)
