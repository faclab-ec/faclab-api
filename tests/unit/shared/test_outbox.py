import contextvars
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.shared.domain.tenant import (
    TenantContext,
    TenantContextRequiredError,
    TenantSource,
    use_tenant,
)
from src.shared.infra.database import Base
from src.shared.infra.outbox import relay as relay_module
from src.shared.infra.outbox.admin import list_failed, retry_failed
from src.shared.infra.outbox.models import OutboxMessageModel, OutboxStatus
from src.shared.infra.outbox.purge import purge_published
from src.shared.infra.outbox.relay import BrokerUnavailableError, OutboxRelay
from src.shared.infra.outbox.writer import OutboxWriter
from tests.conftest import TEST_TENANT_ID

OTHER_TENANT_ID = UUID("00000000-0000-4000-8000-00000000000b")

# The outbox only writes inside a tenant context
pytestmark = pytest.mark.usefixtures("in_tenant")


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[Base.metadata.tables[OutboxMessageModel.__tablename__]]
    )
    return sessionmaker(bind=engine)


class FakePublisher:
    def __init__(self, fail_on: set[str] | None = None, broker_down: bool = False):
        self.sent: list[tuple[str, dict]] = []
        self.fail_on = fail_on or set()
        self.broker_down = broker_down

    def publish(self, topic, value, headers, key=None):
        if self.broker_down:
            raise BrokerUnavailableError("broker unavailable")
        if value["id"] in self.fail_on:
            raise ValueError("message too large")
        self.sent.append((topic, value))

    @property
    def ids(self) -> list[str]:
        return [value["id"] for _, value in self.sent]


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 28, 12, 0)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _write(session_factory, *ids: str, tenant: UUID | None = None) -> None:
    def write() -> None:
        with session_factory() as session:
            writer = OutboxWriter(session)
            for event_id in ids:
                writer.add("topic.a", {"id": event_id}, "Test", event_id)
            session.commit()

    if tenant is None:
        write()
    else:
        with use_tenant(TenantContext(tenant, TenantSource.TASK)):
            write()


def _message(session_factory, event_id: str) -> OutboxMessageModel:
    with session_factory() as session:
        message = session.query(OutboxMessageModel).filter_by(event_id=event_id).one()
        session.expunge(message)
        return message


def test_writer_stores_json_ready_payload(session_factory):
    with session_factory() as session:
        OutboxWriter(session).add(
            "sales.confirmed",
            {"total": Decimal("20.70"), "at": datetime(2026, 10, 8, 12, 0)},
            "SaleConfirmed",
            "evt-1",
        )
        session.commit()
        message = session.query(OutboxMessageModel).one()

    assert message.payload == {"total": "20.70", "at": "2026-10-08T12:00:00"}
    assert (message.status, message.published_at) == (OutboxStatus.PENDING, None)


def test_rolled_back_messages_are_never_published(session_factory):
    with session_factory() as session:
        OutboxWriter(session).add("topic.a", {"id": "x"}, "Test", "x")
        session.rollback()

    publisher = FakePublisher()
    OutboxRelay(session_factory, publisher).publish_pending()

    assert publisher.sent == []


def test_relay_publishes_in_order_and_marks_messages(session_factory):
    _write(session_factory, "a", "b")
    publisher = FakePublisher()

    sent = OutboxRelay(session_factory, publisher).publish_pending()

    assert sent == 2
    assert publisher.ids == ["a", "b"]
    with session_factory() as session:
        messages = session.query(OutboxMessageModel).all()
        assert all(m.status == "published" and m.published_at for m in messages)


def test_a_failing_message_waits_for_its_next_attempt(session_factory):
    _write(session_factory, "a", "b", "c")
    clock = Clock()
    failing = FakePublisher(fail_on={"b"})
    relay = OutboxRelay(session_factory, failing, retry_base_seconds=5, clock=clock)

    assert relay.publish_pending() == 1

    b = _message(session_factory, "b")
    assert (b.status, b.attempts, b.last_error) == ("pending", 1, "message too large")
    assert b.next_attempt_at == clock.now + timedelta(seconds=5)
    # "c" is of the same tenant: it waits behind "b" to keep their order
    assert failing.ids == ["a"]

    working = FakePublisher()
    relay = OutboxRelay(session_factory, working, clock=clock)
    assert relay.publish_pending() == 0
    clock.advance(5)
    assert relay.publish_pending() == 2
    assert working.ids == ["b", "c"]


def test_the_backoff_doubles_up_to_its_maximum(session_factory):
    _write(session_factory, "a")
    clock = Clock()
    relay = OutboxRelay(
        session_factory,
        FakePublisher(fail_on={"a"}),
        max_attempts=10,
        retry_base_seconds=5,
        retry_max_seconds=15,
        clock=clock,
    )

    delays = []
    for _ in range(4):
        relay.publish_pending()
        waits_until = _message(session_factory, "a").next_attempt_at
        assert waits_until is not None
        delays.append((waits_until - clock.now).total_seconds())
        clock.now = waits_until

    assert delays == [5, 10, 15, 15]


def test_a_message_that_always_fails_ends_failed_and_the_rest_go_on(session_factory):
    _write(session_factory, "a", "b", "c")
    _write(session_factory, "x", tenant=OTHER_TENANT_ID)
    clock = Clock()
    publisher = FakePublisher(fail_on={"b"})
    relay = OutboxRelay(
        session_factory, publisher, max_attempts=3, retry_base_seconds=1, clock=clock
    )

    relay.publish_pending()
    # Another tenant doesn't wait for "b"
    assert publisher.ids == ["a", "x"]

    for _ in range(2):
        clock.advance(60)
        relay.publish_pending()

    b = _message(session_factory, "b")
    assert (b.status, b.attempts, b.next_attempt_at) == ("failed", 3, None)
    # Failed, it no longer holds its tenant back
    assert publisher.ids == ["a", "x", "c"]
    assert relay.publish_pending() == 0


def test_a_broker_outage_counts_no_attempt(session_factory):
    _write(session_factory, "a", "b")
    _write(session_factory, "x", tenant=OTHER_TENANT_ID)
    relay = OutboxRelay(session_factory, FakePublisher(broker_down=True))

    with pytest.raises(BrokerUnavailableError):
        relay.publish_pending()

    for event_id in ("a", "b", "x"):
        message = _message(session_factory, event_id)
        assert (message.status, message.attempts) == ("pending", 0)
        assert message.next_attempt_at is None

    working = FakePublisher()
    assert OutboxRelay(session_factory, working).publish_pending() == 3
    assert working.ids == ["a", "b", "x"]


def test_what_was_sent_before_an_outage_stays_published(session_factory):
    _write(session_factory, "a", "b")

    class DownAfterFirst(FakePublisher):
        def publish(self, topic, value, headers, key=None):
            if self.sent:
                raise BrokerUnavailableError("broker unavailable")
            super().publish(topic, value, headers, key)

    with pytest.raises(BrokerUnavailableError):
        OutboxRelay(session_factory, DownAfterFirst()).publish_pending()

    assert _message(session_factory, "a").status == "published"
    assert _message(session_factory, "b").status == "pending"


def test_purge_deletes_only_old_published_messages(session_factory):
    _write(session_factory, "old", "new", "broken", "waiting")
    clock = Clock()
    relay = OutboxRelay(
        session_factory,
        FakePublisher(fail_on={"broken", "waiting"}),
        max_attempts=1,
        clock=clock,
    )
    relay.publish_pending()
    with session_factory() as session:
        old = session.query(OutboxMessageModel).filter_by(event_id="old").one()
        old.published_at = clock.now - timedelta(days=20)
        waiting = session.query(OutboxMessageModel).filter_by(event_id="waiting").one()
        waiting.status = OutboxStatus.PENDING
        session.commit()

    deleted = purge_published(session_factory, clock.now - timedelta(days=14))

    assert deleted == 1
    with session_factory() as session:
        left = {m.event_id: m.status for m in session.query(OutboxMessageModel)}
    assert left == {"new": "published", "broken": "failed", "waiting": "pending"}


def test_a_retried_message_is_published_again_and_audited(session_factory):
    _write(session_factory, "a", "b")
    clock = Clock()
    OutboxRelay(
        session_factory, FakePublisher(fail_on={"a", "b"}), max_attempts=1, clock=clock
    ).publish_pending()
    assert [m.event_id for m in list_failed(session_factory)] == ["a", "b"]
    a = _message(session_factory, "a")

    retried = retry_failed(session_factory, [a.id], by="ops", now=clock.now)

    assert retried == [a.id]
    a = _message(session_factory, "a")
    assert (a.status, a.attempts, a.retried_by, a.retried_at) == (
        "pending",
        0,
        "ops",
        clock.now,
    )
    publisher = FakePublisher()
    OutboxRelay(session_factory, publisher, clock=clock).publish_pending()
    assert publisher.ids == ["a"]
    assert [m.event_id for m in list_failed(session_factory)] == ["b"]


def test_retrying_every_failed_message_leaves_the_others_alone(session_factory):
    _write(session_factory, "a", "b")
    OutboxRelay(
        session_factory, FakePublisher(fail_on={"a"}), max_attempts=1
    ).publish_pending()
    b = _message(session_factory, "b")

    retried = retry_failed(session_factory, None, by="ops")

    assert retried == [_message(session_factory, "a").id]
    assert _message(session_factory, "b").status == b.status == "published"
    assert retry_failed(session_factory, [b.id], by="ops") == []


def test_commit_wakes_the_running_relay(session_factory, monkeypatch):
    woken = []
    monkeypatch.setattr(relay_module, "wake", lambda: woken.append(True))

    with session_factory() as session:
        OutboxWriter(session).add("topic.a", {"id": "a"}, "Test", "a")
        assert woken == []
        session.commit()

    assert woken == [True]


def test_a_message_belongs_to_the_context_tenant(session_factory):
    with session_factory() as session:
        OutboxWriter(session).add("topic.a", {"id": "a"}, "Test", "a")
        session.commit()
        message = session.query(OutboxMessageModel).one()

    assert message.tenant_id == TEST_TENANT_ID
    assert message.headers["faclab-tenant-id"] == str(TEST_TENANT_ID)


def test_the_relay_sends_the_tenant_header(session_factory):
    _write(session_factory, "a")
    publisher = HeaderRecorder()

    OutboxRelay(session_factory, publisher).publish_pending()

    [headers] = publisher.headers
    assert ("faclab-tenant-id", str(TEST_TENANT_ID).encode()) in headers


def test_the_relay_keys_each_message_by_its_tenant(session_factory):
    """A tenant's messages go through the same partition, in order"""
    _write(session_factory, "a", "b")
    publisher = HeaderRecorder()

    OutboxRelay(session_factory, publisher).publish_pending()

    assert publisher.keys == [str(TEST_TENANT_ID), str(TEST_TENANT_ID)]


def test_writing_without_a_tenant_fails(session_factory):
    def write() -> None:
        with session_factory() as session:
            OutboxWriter(session).add("topic.a", {"id": "a"}, "Test", "a")

    # A fresh context: outside the tenant this module's tests run in
    with pytest.raises(TenantContextRequiredError):
        contextvars.Context().run(write)


class HeaderRecorder:
    def __init__(self):
        self.headers: list[list[tuple[str, bytes]]] = []
        self.keys: list[str | None] = []

    def publish(self, topic, value, headers, key=None):
        self.headers.append(headers)
        self.keys.append(key)
