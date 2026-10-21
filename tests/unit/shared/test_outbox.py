import contextvars
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.shared.domain.tenant import TenantContextRequiredError
from src.shared.infra.database import Base
from src.shared.infra.outbox import relay as relay_module
from src.shared.infra.outbox.models import OutboxMessageModel
from src.shared.infra.outbox.relay import OutboxRelay
from src.shared.infra.outbox.writer import OutboxWriter
from tests.conftest import TEST_TENANT_ID

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
    def __init__(self, fail_on: set[str] | None = None):
        self.sent: list[tuple[str, dict]] = []
        self.fail_on = fail_on or set()

    def publish(self, topic, value, headers, key=None):
        if value["id"] in self.fail_on:
            raise ConnectionError("broker unavailable")
        self.sent.append((topic, value))


def _write(session_factory, *ids: str) -> None:
    with session_factory() as session:
        writer = OutboxWriter(session)
        for event_id in ids:
            writer.add("topic.a", {"id": event_id}, "Test", event_id)
        session.commit()


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
    assert message.published_at is None


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
    assert [value["id"] for _, value in publisher.sent] == ["a", "b"]
    with session_factory() as session:
        assert all(m.published_at for m in session.query(OutboxMessageModel))


def test_relay_stops_at_a_failure_and_retries_later(session_factory):
    _write(session_factory, "a", "b", "c")
    failing = FakePublisher(fail_on={"b"})

    assert OutboxRelay(session_factory, failing).publish_pending() == 1

    with session_factory() as session:
        b = session.query(OutboxMessageModel).filter_by(event_id="b").one()
        assert (b.published_at, b.attempts) == (None, 1)
        assert b.last_error == "broker unavailable"

    working = FakePublisher()
    assert OutboxRelay(session_factory, working).publish_pending() == 2
    assert [value["id"] for _, value in working.sent] == ["b", "c"]


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
