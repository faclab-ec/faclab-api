"""Kafka outbox against PostgreSQL: a confirmed sale leaves a message for
faclab-invoicing in the same transaction, and the relay (as faclab_worker)
publishes it; a message that keeps failing ends failed without holding back the
rest, only one relay publishes at a time, and old published messages are
purged."""

from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from config import config
from src.auth.domain.entities import Role
from src.shared.infra.database import worker_session_maker
from src.shared.infra.outbox.admin import retry_failed
from src.shared.infra.outbox.models import OutboxMessageModel, OutboxStatus
from src.shared.infra.outbox.purge import purge_published
from src.shared.infra.outbox.relay import RELAY_LOCK_KEY, OutboxRelay
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    make_location,
    make_movement,
    make_product,
    make_terminal,
    make_warehouse,
    with_key,
)
from tests.integration.postgres.tenants import OTHER_TENANT_RUC, ensure_tenant


class FakePublisher:
    def __init__(self, fail_on: set[str] | None = None):
        self.sent: list[tuple[str, dict, list]] = []
        self.fail_on = fail_on or set()

    def publish(self, topic, value, headers, key=None):
        if value.get("id") in self.fail_on:
            raise ValueError("message too large")
        self.sent.append((topic, value, headers))

    @property
    def ids(self) -> list[str]:
        return [value["id"] for _, value, _ in self.sent]


class Clock:
    def __init__(self):
        self.now = datetime.now()

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture(autouse=True)
def kafka_enabled(monkeypatch):
    monkeypatch.setattr(config, "KAFKA_ENABLED", True)


@pytest.fixture
def pos(client, admin, auth_headers) -> tuple[Api, dict]:
    admin_api = Api(client, admin)
    product = make_product(admin_api, salePrice="10.00")
    location = make_location(admin_api, make_warehouse(admin_api)["id"])
    make_movement(admin_api, product["id"], 5, location["id"])
    terminal = make_terminal(admin_api, location["id"])
    cashier = Api(client, at_terminal(auth_headers(Role.CASHIER), terminal))
    cashier.post("/api/pos/shifts/open", {"openingBalance": "0"})
    return cashier, product


def _checkout(cashier: Api, product_id: int, quantity: int, amount: str):
    return cashier.client.post(
        "/api/pos/sales/quick",
        json={
            "items": [{"productId": product_id, "quantity": quantity}],
            "payments": [{"amount": amount, "paymentMethod": "CASH"}],
        },
        headers=with_key(cashier.headers),
    )


def _messages(db_session: Session) -> list[OutboxMessageModel]:
    return list(db_session.scalars(select(OutboxMessageModel)))


def test_confirmed_sale_is_queued_and_relayed(pos, db_session, tenant):
    cashier, product = pos

    sale = _checkout(cashier, product["id"], 2, "23.00").json()["data"]

    [message] = _messages(db_session)
    assert message.topic == "sales.confirmed"
    assert message.tenant_id == tenant
    assert message.published_at is None
    assert message.payload["payload"]["sale_id"] == sale["id"]
    assert message.payload["payload"]["total"] == "23.00"
    assert message.payload["payload"]["items"][0]["sku"] == product["sku"]

    publisher = FakePublisher()
    assert OutboxRelay(worker_session_maker(), publisher).publish_pending() == 1

    [(topic, value, headers)] = publisher.sent
    assert (topic, value) == ("sales.confirmed", message.payload)
    assert ("faclab-tenant-id", str(tenant).encode()) in headers
    db_session.expire_all()
    assert _messages(db_session)[0].published_at is not None


def test_failed_sale_queues_nothing(pos, db_session):
    cashier, product = pos

    response = _checkout(cashier, product["id"], 6, "69.00")

    assert response.status_code == 400
    assert _messages(db_session) == []


def _queue(db_session: Session, tenant_id: UUID, *ids: str) -> None:
    """Messages as OutboxWriter leaves them, written as the superuser"""
    for event_id in ids:
        db_session.add(
            OutboxMessageModel(
                event_id=event_id,
                event_type="Test",
                topic="sales.confirmed",
                payload={"id": event_id},
                tenant_id=tenant_id,
                headers={"faclab-tenant-id": str(tenant_id)},
                status=OutboxStatus.PENDING.value,
            )
        )
    db_session.commit()


def _status(db_session: Session, event_id: str) -> tuple[str, int]:
    db_session.expire_all()
    message = db_session.scalars(
        select(OutboxMessageModel).where(OutboxMessageModel.event_id == event_id)
    ).one()
    return message.status, message.attempts


def test_a_message_that_always_fails_ends_failed_and_the_rest_go_on(
    db_session, tenant, pg_engine
):
    other = ensure_tenant(pg_engine, OTHER_TENANT_RUC)
    _queue(db_session, tenant, "a", "b", "c")
    _queue(db_session, other, "x")
    clock = Clock()
    publisher = FakePublisher(fail_on={"b"})
    relay = OutboxRelay(
        worker_session_maker(),
        publisher,
        max_attempts=3,
        retry_base_seconds=10,
        clock=clock,
    )

    relay.publish_pending()
    # The other tenant doesn't wait; "c" waits behind "b", its tenant's order
    assert publisher.ids == ["a", "x"]
    assert _status(db_session, "b") == ("pending", 1)
    assert relay.publish_pending() == 0

    for _ in range(2):
        clock.now += timedelta(minutes=5)
        relay.publish_pending()

    assert _status(db_session, "b") == ("failed", 3)
    assert publisher.ids == ["a", "x", "c"]

    # Put back by hand, it is published again and the retry is recorded
    [b_id] = db_session.scalars(
        select(OutboxMessageModel.id).where(OutboxMessageModel.event_id == "b")
    )
    assert retry_failed(worker_session_maker(), [b_id], by="ops") == [b_id]
    publisher.fail_on.clear()
    assert relay.publish_pending() == 1
    assert publisher.ids[-1] == "b"
    db_session.expire_all()
    b = db_session.get(OutboxMessageModel, b_id)
    assert b is not None
    assert (b.status, b.retried_by) == ("published", "ops")


def test_one_relay_publishes_at_a_time(db_session, tenant):
    """The API and the worker during a deploy, or two workers: the order of a
    tenant's messages holds because only one of them publishes"""
    _queue(db_session, tenant, "a")
    publisher = FakePublisher()

    with worker_session_maker()() as other_relay:
        other_relay.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": RELAY_LOCK_KEY}
        )
        assert OutboxRelay(worker_session_maker(), publisher).publish_pending() == 0
        other_relay.rollback()

    assert OutboxRelay(worker_session_maker(), publisher).publish_pending() == 1
    assert publisher.ids == ["a"]


def test_old_published_messages_are_purged(db_session, tenant):
    _queue(db_session, tenant, "old", "new", "waiting")
    OutboxRelay(
        worker_session_maker(), FakePublisher(fail_on={"waiting"})
    ).publish_pending()
    db_session.execute(
        text(
            "UPDATE outbox_messages SET published_at = now() - interval '20 days' "
            "WHERE event_id = 'old'"
        )
    )
    db_session.commit()

    deleted = purge_published(
        worker_session_maker(), datetime.now() - timedelta(days=14)
    )

    assert deleted == 1
    left = set(db_session.scalars(select(OutboxMessageModel.event_id)))
    assert left == {"new", "waiting"}
