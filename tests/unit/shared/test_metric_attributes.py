"""S7.1 acceptance: every metric the session added is emitted through its real
code path with its name and unit, and none carries an id as an attribute
(OBSERVABILITY.md §6: never the id of a tenant, sale, user, customer, product
or invoice). Its keys are exactly the bounded ones of the standard."""

import asyncio
import re
import threading
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.auth.domain.exceptions import LoginFailedError
from src.auth.infra.metrics import login_attempt
from src.background import queue_metrics
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.inventory.movement.infra.mappers import MovementMapper
from src.inventory.movement.infra.metrics import stock_attempt
from src.inventory.movement.infra.models import MovementModel
from src.inventory.movement.infra.repositories import SqlAlchemyMovementRepository
from src.inventory.stock.domain.exceptions import InsufficientStockError
from src.invoicing.infra import reconciliation
from src.invoicing.infra.models import InvoiceDiscrepancyModel
from src.pos.infra.event_handlers import (
    count_refund_completed,
    count_sale_cancelled,
    count_sale_confirmed,
)
from src.pos.infra.metrics import sale_attempt
from src.pos.refund.domain.events import RefundCompleted
from src.sales.domain.events import SaleCancelled, SaleConfirmed
from src.sales.domain.exceptions import InsufficientStockError as SaleStockError
from src.shared.infra import database
from src.shared.infra.database import Base, create_session_maker
from src.shared.infra.kafka.consumer import KafkaMessageConsumer
from src.shared.infra.kafka.models import DeadLetterModel
from src.shared.infra.kafka.producer import KafkaEventProducer
from src.shared.infra.outbox.models import OutboxMessageModel, OutboxStatus
from tests.sqlite import sqlite_session

pytestmark = pytest.mark.usefixtures("in_tenant")

TENANT_ID = UUID("00000000-0000-4000-8000-0000000000a1")
SOURCE = "faclab.sale.source"
TOPIC = "messaging.destination.name"
KAFKA = {"messaging.system", "messaging.operation.name", TOPIC}

# name: (unit, keys every point has, keys a point may add)
CATALOG: dict[str, tuple[str, set[str], set[str]]] = {
    "faclab.outbox.pending": ("{message}", {TOPIC}, set()),
    "faclab.outbox.oldest_age": ("s", {TOPIC}, set()),
    "faclab.outbox.failed": ("{message}", {TOPIC}, set()),
    "faclab.dead_letters.pending": ("{message}", {TOPIC}, set()),
    "faclab.reconciliation.discrepancies": ("{discrepancy}", {"kind"}, set()),
    "db.client.connection.count": (
        "{connection}",
        {"db.client.connection.pool.name", "db.client.connection.state"},
        set(),
    ),
    "faclab.auth.login.attempts": ("{attempt}", {"result"}, set()),
    "faclab.sales.confirmed": ("{sale}", {SOURCE}, set()),
    "faclab.sales.failed": ("{sale}", {"error.code", SOURCE}, set()),
    "faclab.sales.cancelled": ("{sale}", {SOURCE}, set()),
    "faclab.refunds.completed": ("{refund}", {SOURCE}, set()),
    "faclab.inventory.movements": (
        "{movement}",
        {"faclab.movement.type", "faclab.movement.source"},
        set(),
    ),
    "faclab.inventory.stock_rejections": (
        "{rejection}",
        {"faclab.movement.source"},
        set(),
    ),
    "messaging.client.sent.messages": ("{message}", KAFKA, {"error.type"}),
    "messaging.process.duration": (
        "s",
        KAFKA | {"messaging.consumer.group.name"},
        {"error.type"},
    ),
}

_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def _committed(*emit) -> None:
    session = create_session_maker("sqlite://")()
    session.execute(text("SELECT 1"))
    for function, event in emit:
        function(event, session=session)
    session.commit()


def _sales() -> None:
    _committed(
        (
            count_sale_confirmed,
            SaleConfirmed(aggregate_id=41, sale_id=41, source="pos"),
        ),
        (
            count_sale_cancelled,
            SaleCancelled(
                aggregate_id=41, sale_id=41, was_confirmed=True, source="pos"
            ),
        ),
        (
            count_refund_completed,
            RefundCompleted(aggregate_id=8, refund_id=8, original_sale_id=41),
        ),
    )
    with pytest.raises(SaleStockError), sale_attempt("api"):
        raise SaleStockError(product_id=77, requested=Decimal(3), available=Decimal(1))


def _inventory() -> None:
    session = sqlite_session([MovementModel])
    SqlAlchemyMovementRepository(session, MovementMapper()).create(
        Movement(
            product_id=77,
            quantity=Decimal(-1),
            type=MovementType.OUT,
            location_id=5,
            reference_type="sale",
            reference_id=41,
        )
    )
    session.commit()
    with pytest.raises(InsufficientStockError), stock_attempt("transfer"):
        raise InsufficientStockError(77, Decimal(2))


def _login() -> None:
    with login_attempt():
        pass
    with pytest.raises(LoginFailedError), login_attempt():
        raise LoginFailedError()


def _worker_factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables[model.__tablename__]
            for model in (OutboxMessageModel, DeadLetterModel)
        ],
    )
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(
            OutboxMessageModel(
                event_id="e-1",
                event_type="SaleConfirmed",
                topic="sales.confirmed",
                payload={"sale_id": 41},
                tenant_id=TENANT_ID,
                headers={},
                status=OutboxStatus.PENDING.value,
            )
        )
        session.commit()
    return factory


def _queues() -> None:
    queue_metrics.sample_queues(
        _worker_factory(),
        ("sales.confirmed", "credit_notes.requested"),
        ("invoices", "credit_notes.results"),
        max_age=180,
    )


def _reconciliation(monkeypatch) -> None:
    session = sqlite_session([InvoiceDiscrepancyModel])
    factory = sessionmaker(bind=session.get_bind())
    monkeypatch.setattr(database, "worker_session_maker", lambda: factory)
    monkeypatch.setattr(reconciliation, "tenants_to_reconcile", lambda *_: [])
    reconciliation.reconcile()


def _pool(tmp_path) -> sessionmaker:
    """Returned so the engine lives until the collection: pools are watched
    through a weak reference"""
    factory = create_session_maker(f"sqlite:///{tmp_path}/pool.sqlite", pool_name="t")
    with factory() as session:
        session.execute(text("SELECT 1"))
    return factory


class _Broker:
    async def send_and_wait(self, topic, value, key=None, headers=None):
        return None


def _messaging() -> None:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        producer = KafkaEventProducer("localhost:9092")
        producer._loop = loop
        producer._producer = _Broker()  # ty: ignore[invalid-assignment]
        producer.publish(
            "sales.confirmed", {"event_id": "e-41"}, [], key=str(TENANT_ID)
        )
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()

    def failing(_message):
        raise ConnectionError("database is down")

    consumer = KafkaMessageConsumer(
        "localhost:9092", "faclab-core", {"invoices": failing}
    )
    consumer.process(
        "invoices",
        b'{"sale_id": 41, "invoice_id": "i-1"}',
        [("faclab-tenant-id", str(TENANT_ID).encode())],
        partition=3,
        offset=99,
    )


def _looks_like_an_id(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return True
    return bool(_UUID.match(str(value))) or str(value).isdigit()


def test_every_new_metric_is_emitted_with_bounded_attributes(
    recorded_metrics, monkeypatch, tmp_path
):
    _sales()
    _inventory()
    _login()
    _queues()
    _reconciliation(monkeypatch)
    pool = _pool(tmp_path)
    _messaging()

    collected = recorded_metrics.collect()
    del pool

    for name, (unit, required, optional) in CATALOG.items():
        points = collected.points(name)
        assert points, f"{name} was not emitted"
        assert collected.units[name] == unit, name
        for _value, attributes in points:
            keys = set(attributes)
            assert required <= keys <= required | optional, (name, attributes)
            for key, value in attributes.items():
                assert not key.endswith("id"), (name, key)
                assert not _looks_like_an_id(value), (name, key, value)
