"""One sale, one trace (OBSERVABILITY.md §5.1, §10; S7.6).

A POS sale goes through the real app on PostgreSQL with the OTel middleware,
its outbox message through the relay and the real Kafka producer (a fake
broker behind it), and faclab-invoicing's answer through the real consumer.
Every step is a span of the same trace, the child of the step before, with the
attributes §5.2 fixes, and the logs written on the way carry that trace and
their `event.name`. Dropping an `inject`/`extract` or a span fails here."""

import asyncio
import json
import uuid

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanContext, SpanKind, TraceFlags
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from config import config
from src.auth.domain.entities import Role
from src.background.messaging import CONSUMER_HANDLERS
from src.invoicing.infra.invoice_messages import INVOICES_TOPIC
from src.shared.infra.database import worker_session_maker
from src.shared.infra.kafka.consumer import KafkaMessageConsumer
from src.shared.infra.outbox.models import OutboxMessageModel
from src.shared.infra.outbox.relay import OutboxRelay
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    make_location,
    make_movement,
    make_product,
    make_terminal,
    make_warehouse,
)
from tests.kafka import fake_producer
from tests.telemetry import (
    assert_child_of,
    children_of,
    descends_from,
    one,
    span_ids,
    traceparent_ids,
    traceparent_of,
)


@pytest.fixture(autouse=True)
def kafka_enabled(monkeypatch):
    monkeypatch.setattr(config, "KAFKA_ENABLED", True)


@pytest.fixture
def pos(traced_client, admin, auth_headers) -> tuple[Api, dict, dict]:
    admin_api = Api(traced_client, admin)
    product = make_product(admin_api, salePrice="10.00")
    location = make_location(admin_api, make_warehouse(admin_api)["id"])
    make_movement(admin_api, product["id"], 5, location["id"])
    terminal = make_terminal(admin_api, location["id"])
    cashier = Api(traced_client, at_terminal(auth_headers(Role.CASHIER), terminal))
    cashier.post("/api/pos/shifts/open", {"openingBalance": "0"})
    return cashier, product, terminal


def _attributes(span: ReadableSpan) -> dict:
    return dict(span.attributes or {})


def test_a_sale_and_its_invoice_are_one_trace(
    pos, tenant, db_session: Session, span_exporter, json_logs
):
    cashier, product, terminal = pos
    span_exporter.clear()

    # 1. The POS request: a SERVER span with its route, tenant and branch;
    # the commands and the SaleConfirmed event run inside it
    sale = cashier.post(
        "/api/pos/sales/quick",
        {
            "items": [{"productId": product["id"], "quantity": 2}],
            "payments": [{"amount": "23.00", "paymentMethod": "CASH"}],
        },
    )
    spans = span_exporter.get_finished_spans()
    request = one(spans, "POST /api/pos/sales/quick")
    assert request.kind == SpanKind.SERVER
    assert _attributes(request) | {
        "http.request.method": "POST",
        "http.route": "/api/pos/sales/quick",
        "http.response.status_code": 201,
        "faclab.tenant.id": str(tenant),
        "faclab.branch.id": terminal["branchId"],
    } == _attributes(request)
    trace_id, _ = span_ids(request)

    commands = [span for span in spans if span.name.startswith("command.")]
    assert commands
    assert all(descends_from(spans, span, request) for span in commands)
    published = one(spans, "event.publish.SaleConfirmed")
    assert _attributes(published)["event.type"] == "SaleConfirmed"
    assert descends_from(spans, published, request)
    handled = children_of(spans, published)
    assert handled
    for span in handled:
        assert span.name.startswith("event.handle.")
        assert _attributes(span)["event.type"] == "SaleConfirmed"

    # 2. The outbox keeps the context of the span that wrote the message
    [message] = db_session.scalars(select(OutboxMessageModel)).all()
    stored_trace, writer_id = traceparent_ids(message.headers["traceparent"])
    assert stored_trace == trace_id
    writer = next(span for span in spans if span_ids(span)[1] == writer_id)
    assert descends_from(spans, writer, request)

    # 3. The relay sends it from a PRODUCER span, child of that context, and
    # the message carries the send span to faclab-invoicing
    with fake_producer() as (producer, broker):
        assert OutboxRelay(worker_session_maker(), producer).publish_pending() == 1
    spans = span_exporter.get_finished_spans()
    send = one(spans, "send sales.confirmed")
    assert send.kind == SpanKind.PRODUCER
    assert_child_of(send, writer)
    assert _attributes(send) | {
        "messaging.system": "kafka",
        "messaging.destination.name": "sales.confirmed",
        "messaging.message.id": message.event_id,
        "messaging.kafka.message.key": str(tenant),
    } == _attributes(send)
    [(_topic, _value, sent_headers)] = broker.sent
    assert traceparent_ids(dict(sent_headers)["traceparent"]) == span_ids(send)

    # 4. faclab-invoicing answers from a span of that same trace (its
    # `send invoices`); the consumer continues it and the sale is invoiced
    assert send.context is not None
    invoicing = SpanContext(
        trace_id=send.context.trace_id,
        span_id=0x5EED5EED5EED5EED,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    authorized = {
        "type": "InvoiceAuthorized",
        "invoiceId": str(uuid.uuid4()),
        "saleId": str(sale["id"]),
        "status": "authorized",
        "occurredAt": "2026-11-22T15:00:00.000Z",
    }
    consumer = KafkaMessageConsumer("kafka:9092", "faclab-core", CONSUMER_HANDLERS)
    assert asyncio.run(
        consumer.handle(
            INVOICES_TOPIC,
            json.dumps(authorized).encode(),
            [
                ("traceparent", traceparent_of(invoicing).encode()),
                ("faclab-tenant-id", str(tenant).encode()),
            ],
            partition=3,
            offset=8,
            key=str(tenant).encode(),
        )
    )
    spans = span_exporter.get_finished_spans()
    process = one(spans, "process invoices")
    assert process.kind == SpanKind.CONSUMER
    assert_child_of(process, invoicing)
    assert _attributes(process) | {
        "messaging.system": "kafka",
        "messaging.destination.name": INVOICES_TOPIC,
        "messaging.consumer.group.name": "faclab-core",
        "messaging.kafka.message.key": str(tenant),
        "faclab.tenant.id": str(tenant),
    } == _attributes(process)
    invoice_sale = one(spans, "command.InvoiceSaleCommand")
    assert_child_of(invoice_sale, process)
    status = db_session.execute(
        text("SELECT status, invoice_status FROM sales WHERE id = :id"),
        {"id": sale["id"]},
    ).one()
    assert tuple(status) == ("INVOICED", "AUTHORIZED")

    # 5. One trace from the cashier to the invoice, and its logs say so
    for span in (request, published, writer, send, process, invoice_sale):
        assert span_ids(span)[0] == trace_id
    logs = json_logs.of_trace(trace_id)
    written = {line["event"] for line in logs}
    # The request, the relay's send and the consumer's processing
    assert {"command_completed", "event_published", "kafka_message_sent"} <= written
    assert "command_completed" in {
        line["event"] for line in logs if line["span_id"] == span_ids(invoice_sale)[1]
    }
    finished = {span_ids(span)[1] for span in spans}
    for line in logs:
        assert line["span_id"] in finished
        assert line["event.name"] == line["event"].replace("_", ".")
