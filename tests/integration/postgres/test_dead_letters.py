"""The core's Kafka consumer against PostgreSQL: an `invoices` message whose
handler keeps failing ends in dead_letters (as faclab_worker), the consumer goes
on with the next one, and the dead letter is reprocessed through the same
handler."""

import asyncio
import json
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.background.messaging import CONSUMER_HANDLERS
from src.invoicing.infra.invoice_messages import INVOICES_TOPIC
from src.sales.app.commands.invoice_sale import InvoiceSaleCommandHandler
from src.sales.infra.models import SaleModel
from src.shared.infra.database import worker_session_maker
from src.shared.infra.kafka.consumer import KafkaMessageConsumer
from src.shared.infra.kafka.dead_letters import DeadLetterStore, list_pending, reprocess
from src.shared.infra.kafka.models import DeadLetterModel


def _sale(pg_engine, tenant: UUID) -> int:
    with Session(bind=pg_engine) as session:
        sale = SaleModel(tenant_id=tenant, status="CONFIRMED", invoice_status="PENDING")
        session.add(sale)
        session.commit()
        return sale.id


def _authorized(sale_id: int) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "type": "InvoiceAuthorized",
            "invoiceId": f"invoice-{sale_id}",
            "saleId": str(sale_id),
            "status": "authorized",
            "occurredAt": "2026-10-28T15:00:00.000Z",
        }
    ).encode()


def _status(db_session: Session, sale_id: int) -> tuple[str, str | None]:
    db_session.expire_all()
    sale = db_session.get(SaleModel, sale_id)
    assert sale is not None
    return sale.status, sale.invoice_status


@pytest.fixture
def broken_sales(monkeypatch) -> set[int]:
    """Sales whose invoicing fails, as with a lock or a bug"""
    broken: set[int] = set()
    original = InvoiceSaleCommandHandler._handle

    def handle(self, command):
        if command.sale_id in broken:
            raise RuntimeError(f"sale {command.sale_id} is locked")
        return original(self, command)

    monkeypatch.setattr(InvoiceSaleCommandHandler, "_handle", handle)
    return broken


def test_a_message_that_keeps_failing_ends_in_dead_letters_and_the_next_goes_on(
    pg_engine, db_session, tenant, broken_sales
):
    stuck, next_one = _sale(pg_engine, tenant), _sale(pg_engine, tenant)
    broken_sales.add(stuck)
    consumer = KafkaMessageConsumer(
        "kafka:9092",
        "faclab-core",
        CONSUMER_HANDLERS,
        dead_letters=DeadLetterStore(worker_session_maker()),
        max_attempts=3,
        retry_base_delay=0,
    )
    headers = [("faclab-tenant-id", str(tenant).encode())]

    async def consume() -> list[bool]:
        return [
            await consumer.handle(
                INVOICES_TOPIC, _authorized(sale_id), headers, partition=0, offset=n
            )
            for n, sale_id in enumerate((stuck, next_one))
        ]

    # Both offsets can be committed: the partition doesn't stop at the first
    assert asyncio.run(consume()) == [True, True]

    assert _status(db_session, stuck) == ("CONFIRMED", "PENDING")
    assert _status(db_session, next_one) == ("INVOICED", "AUTHORIZED")
    [letter] = db_session.scalars(select(DeadLetterModel)).all()
    assert (letter.topic, letter.kafka_partition, letter.kafka_offset) == (
        INVOICES_TOPIC,
        0,
        0,
    )
    assert (letter.tenant_id, letter.attempts, letter.status) == (tenant, 3, "pending")
    assert letter.headers == {"faclab-tenant-id": str(tenant)}
    assert letter.error == f"sale {stuck} is locked"
    assert json.loads(letter.value or "")["saleId"] == str(stuck)

    # Fixed, it is reprocessed by hand and the reprocess is recorded
    broken_sales.clear()
    [pending] = list_pending(worker_session_maker())
    done = reprocess(worker_session_maker(), pending.id, "ops", consumer.dispatch)

    assert done is not None
    assert (done.status, done.reprocessed_by) == ("reprocessed", "ops")
    assert _status(db_session, stuck) == ("INVOICED", "AUTHORIZED")
    assert list_pending(worker_session_maker()) == []
