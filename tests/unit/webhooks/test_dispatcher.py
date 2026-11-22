"""The worker's sending of the webhooks (S6.4) against local HTTPS receivers,
over a SQLite file the dispatcher opens its own sessions on, like the worker."""

import json
import time
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from opentelemetry.trace import SpanKind, StatusCode
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from src.auth.domain.entities import Role
from src.auth.infra.models import UserModel
from src.shared.app.mail import Mailer, OutgoingMail
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.shared.infra.database import Base, create_session_maker
from src.tenancy.infra.models import MembershipModel, TenantModel
from src.webhooks.domain.entities import RETRY_SCHEDULE, DisabledReason
from src.webhooks.domain.types import WebhookEventType
from src.webhooks.infra.dispatcher import WebhookDispatcher
from src.webhooks.infra.http import WebhookSender
from src.webhooks.infra.models import (
    WebhookDeliveryModel,
    WebhookEndpointModel,
    WebhookMessageModel,
)
from src.webhooks.infra.notifications import DisabledEndpointNotifier
from src.webhooks.infra.purge import purge_history
from src.webhooks.infra.urls import DnsUrlGuard
from tests.conftest import TEST_TENANT_ID
from tests.telemetry import named, span_ids
from tests.webhook_receiver import Receiver
from tests.webhooks_kit import WEBHOOK_MODELS, Kit, fernet_box, table_resolver

LOCAL = DnsUrlGuard(
    resolver=table_resolver({"localhost": ["127.0.0.1"]}), allow_private=True
)
TENANT = TenantContext(TEST_TENANT_ID, TenantSource.REQUEST)
BOX = fernet_box()


class Clock:
    """The worker's: a minute ahead, so what the tenant enqueues now is due"""

    def __init__(self):
        self.now = datetime.now() + timedelta(minutes=1)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class FakeMailer(Mailer):
    def __init__(self):
        self.sent: list[OutgoingMail] = []

    def send(self, mail: OutgoingMail) -> None:
        self.sent.append(mail)


@pytest.fixture
def factory(tmp_path) -> sessionmaker[Session]:
    factory = create_session_maker(f"sqlite:///{tmp_path}/webhooks.db")
    models = [TenantModel, UserModel, MembershipModel, *WEBHOOK_MODELS]
    Base.metadata.create_all(
        factory.kw["bind"],
        tables=[Base.metadata.tables[model.__tablename__] for model in models],
    )
    with factory() as session:
        session.add(
            TenantModel(id=TEST_TENANT_ID, ruc="1799999990001", legal_name="Ferretería")
        )
        session.add_all(
            [
                UserModel(
                    id=1, username="admin", email="admin@ferre.ec", password_hash="x"
                ),
                UserModel(
                    id=2, username="caja", email="caja@ferre.ec", password_hash="x"
                ),
                MembershipModel(
                    tenant_id=TEST_TENANT_ID, user_id=1, role=Role.ADMIN.value
                ),
                MembershipModel(
                    tenant_id=TEST_TENANT_ID, user_id=2, role=Role.CASHIER.value
                ),
            ]
        )
        session.commit()
    return factory


class World:
    """The tenant's side (endpoints, events) and the worker's (the dispatcher)"""

    def __init__(self, factory: sessionmaker[Session], certificate):
        self.factory = factory
        self.clock = Clock()
        self.mailer = FakeMailer()
        self.disabled: list[dict] = []
        notifier = DisabledEndpointNotifier(factory, self.mailer)

        def notify(tenant_id: UUID, endpoint: dict) -> None:
            self.disabled.append(endpoint)
            notifier(tenant_id, endpoint)

        self.dispatcher = WebhookDispatcher(
            factory,
            WebhookSender(LOCAL, timeout=3.0, tls=certificate.client_context()),
            BOX,
            concurrency=4,
            poll_interval=0.05,
            clock=self.clock,
            disabler=self._disable,
            notifier=notify,
        )

    def _disable(self, tenant_id: UUID, endpoint_id: int) -> dict | None:
        with use_tenant(TenantContext(tenant_id, TenantSource.TASK)):
            return self.as_tenant(lambda kit: kit.disable_failing(endpoint_id))

    def as_tenant(self, work):
        with use_tenant(TENANT), self.factory() as session:
            result = work(Kit(session, box=BOX, guard=LOCAL))
            session.commit()
            return result

    def endpoint(self, receiver: Receiver, **kw) -> dict:
        endpoint = self.as_tenant(lambda kit: kit.create(url=receiver.url, **kw))
        receiver.secrets = [
            self.as_tenant(lambda kit: kit.secret(endpoint["id"]))["secret"]
        ]
        return endpoint

    def sale(self, sale_id: int = 1) -> None:
        self.as_tenant(
            lambda kit: kit.outbox.enqueue(
                WebhookEventType.SALE_CONFIRMED, {"saleId": sale_id}, branch_id=12
            )
        )

    def delivery(self, endpoint_id: int, index: int = 0) -> WebhookDeliveryModel:
        with self.factory() as session:
            rows = session.scalars(
                select(WebhookDeliveryModel)
                .where(WebhookDeliveryModel.endpoint_id == endpoint_id)
                .order_by(WebhookDeliveryModel.id)
            ).all()
            session.expunge_all()
            return rows[index]

    def get(self, endpoint_id: int) -> dict:
        return self.as_tenant(lambda kit: kit.get(endpoint_id))


@pytest.fixture
def world(factory, certificate) -> World:
    return World(factory, certificate)


def test_a_signed_message_is_delivered_and_the_receiver_verifies_it(world, receiver):
    endpoint = world.endpoint(receiver)
    world.sale()

    [outcome] = world.dispatcher.run_once()

    assert outcome.status == "delivered"
    [got] = receiver.received
    assert got.verified
    with world.factory() as session:
        message = session.scalars(select(WebhookMessageModel)).one()
    assert got.headers["webhook-id"] == message.public_id
    assert json.loads(got.body) == message.payload
    assert abs(int(got.headers["webhook-timestamp"]) - time.time()) < 5
    delivery = world.delivery(endpoint["id"])
    assert (delivery.status, delivery.attempts, delivery.response_status) == (
        "delivered",
        1,
        204,
    )
    assert delivery.locked_until is None
    assert world.get(endpoint["id"])["last_success_at"] == world.clock.now
    # Nothing left
    assert world.dispatcher.run_once() == []


def test_a_down_endpoint_is_retried_disabled_and_resent_once_enabled(world, receiver):
    receiver.status = 500
    endpoint = world.endpoint(receiver)
    world.sale()

    waits = []
    for _ in range(len(RETRY_SCHEDULE)):
        [outcome] = world.dispatcher.run_once()
        assert outcome.status == "pending"
        delivery = world.delivery(endpoint["id"])
        waits.append(delivery.next_attempt_at - world.clock.now)
        # Not before its time
        world.clock.advance(waits[-1] - timedelta(seconds=1))
        assert world.dispatcher.run_once() == []
        world.clock.advance(timedelta(seconds=1))
    [last] = world.dispatcher.run_once()

    assert waits == list(RETRY_SCHEDULE)
    assert (last.status, last.disabled) == ("failed", True)
    assert len(receiver.received) == 9 and all(r.verified for r in receiver.received)
    shown = world.get(endpoint["id"])
    assert (shown["status"], shown["disabled_reason"]) == (
        "disabled",
        DisabledReason.FAILING,
    )
    assert shown["failing_since"] is not None
    # The company's administrators are told, not the cashier
    [mail] = world.mailer.sent
    assert mail.to == "admin@ferre.ec"
    assert mail.sender_name == "Ferretería"
    assert receiver.url.split("?")[0] in mail.text
    # Disabled: new events don't reach it
    world.sale(2)
    assert world.dispatcher.run_once() == []

    # Enabled again, the failed delivery is sent by hand and goes through
    receiver.status = 204
    world.as_tenant(lambda kit: kit.enable(endpoint["id"]))
    delivery_id = world.delivery(endpoint["id"]).id
    world.as_tenant(lambda kit: kit.retry(endpoint["id"], delivery_id))
    [resent] = world.dispatcher.run_once()

    assert resent.status == "delivered"
    assert (
        receiver.received[-1].headers["webhook-id"]
        == (receiver.received[0].headers["webhook-id"])
    )
    assert world.get(endpoint["id"])["status"] == "active"


def test_an_endpoint_that_answered_since_the_delivery_stays_enabled(world, receiver):
    receiver.status = 500
    endpoint = world.endpoint(receiver)
    world.sale()
    with world.factory() as session:
        session.execute(
            update(WebhookDeliveryModel).values(attempts=len(RETRY_SCHEDULE))
        )
        session.execute(
            update(WebhookEndpointModel).values(
                last_success_at=world.clock.now + timedelta(seconds=1)
            )
        )
        session.commit()

    [outcome] = world.dispatcher.run_once()

    assert (outcome.status, outcome.disabled) == ("failed", False)
    assert world.get(endpoint["id"])["status"] == "active"
    assert world.mailer.sent == []


def test_one_delivery_at_a_time_per_endpoint(world, receiver, certificate):
    first = world.endpoint(receiver)
    other_receiver = Receiver(certificate)
    try:
        second = world.endpoint(other_receiver)
        world.sale(1)
        world.sale(2)

        claims = world.dispatcher.claim(10)
        assert sorted(c.endpoint_id for c in claims) == [first["id"], second["id"]]
        # Their leases hold the other deliveries of both endpoints
        assert world.dispatcher.claim(10) == []
        for claim in claims:
            world.dispatcher.deliver(claim)
        assert len(world.dispatcher.run_once()) == 2
        assert len(receiver.received) == len(other_receiver.received) == 2
    finally:
        other_receiver.close()


def test_the_lease_of_a_worker_that_died_expires(world, receiver):
    endpoint = world.endpoint(receiver)
    world.sale()
    [claim] = world.dispatcher.claim(1)

    assert world.dispatcher.claim(1) == []
    world.clock.advance(timedelta(minutes=1))
    [again] = world.dispatcher.claim(1)

    assert again.delivery_id == claim.delivery_id
    assert world.delivery(endpoint["id"]).attempts == 2


def test_a_slow_receiver_does_not_hold_back_another_endpoint(
    world, receiver, certificate
):
    receiver.delay = 1.5
    slow = world.endpoint(receiver)
    fast_receiver = Receiver(certificate)
    try:
        fast = world.endpoint(fast_receiver)
        world.sale()
        world.dispatcher.start()
        deadline = time.monotonic() + 1.0
        while not fast_receiver.received and time.monotonic() < deadline:
            time.sleep(0.02)
        delivered_fast = world.delivery(fast["id"]).status
        slow_status = world.delivery(slow["id"]).status
    finally:
        world.dispatcher.stop()
        fast_receiver.close()

    assert fast_receiver.received and delivered_fast in ("pending", "delivered")
    assert slow_status == "pending"
    assert world.delivery(slow["id"]).status == "delivered"
    assert world.delivery(fast["id"]).status == "delivered"


def test_during_a_rotation_the_previous_secret_still_verifies(world, receiver):
    endpoint = world.endpoint(receiver)
    previous = receiver.secrets
    world.as_tenant(lambda kit: kit.rotate(endpoint["id"], hours=24))
    world.sale()

    world.dispatcher.run_once()

    [got] = receiver.received
    assert got.verified
    assert len(got.headers["webhook-signature"].split(" ")) == 2
    assert receiver.secrets == previous


def test_a_deleted_endpoint_s_claim_sends_nothing(world, receiver):
    endpoint = world.endpoint(receiver)
    world.sale()
    [claim] = world.dispatcher.claim(1)
    world.as_tenant(lambda kit: kit.delete(endpoint["id"]))

    assert world.dispatcher.deliver(claim) is None
    assert receiver.received == []


def test_the_history_older_than_the_retention_is_purged(world, receiver):
    endpoint = world.endpoint(receiver)
    world.sale(1)
    world.sale(2)
    old = world.delivery(endpoint["id"])
    with world.factory() as session:
        session.execute(
            update(WebhookDeliveryModel)
            .where(WebhookDeliveryModel.id == old.id)
            .values(created_at=datetime.now() - timedelta(days=31))
        )
        session.execute(
            update(WebhookMessageModel)
            .where(WebhookMessageModel.id == old.message_id)
            .values(created_at=datetime.now() - timedelta(days=31))
        )
        session.commit()

    assert purge_history(world.factory, datetime.now() - timedelta(days=30)) == 1

    with world.factory() as session:
        assert len(session.scalars(select(WebhookDeliveryModel)).all()) == 1
        assert len(session.scalars(select(WebhookMessageModel)).all()) == 1


# --- Telemetry (S7.6, OBSERVABILITY.md §5.2 and §10) ---------------------------


def test_each_attempt_is_a_webhook_deliver_span_with_its_log(
    world, receiver, span_exporter, json_logs
):
    receiver.status = 500
    endpoint = world.endpoint(receiver)
    world.sale()

    [first] = world.dispatcher.run_once()
    world.clock.advance(
        world.delivery(endpoint["id"]).next_attempt_at - world.clock.now
    )
    receiver.status = 204
    [second] = world.dispatcher.run_once()

    assert (first.status, second.status) == ("pending", "delivered")
    failed, delivered = named(span_exporter.get_finished_spans(), "webhook.deliver")
    for span, attempt, status in ((failed, 1, 500), (delivered, 2, 204)):
        assert span.kind == SpanKind.CLIENT
        assert span.attributes is not None
        assert span.attributes["faclab.retry.attempt"] == attempt
        assert span.attributes["http.response.status_code"] == status
        assert span.attributes["server.address"] == "localhost"
        assert span.attributes["faclab.webhook.event_type"] == "sale.confirmed"
        assert span.attributes["faclab.tenant.id"] == str(TEST_TENANT_ID)
    assert failed.status.status_code == StatusCode.ERROR
    assert delivered.status.status_code != StatusCode.ERROR

    # The log of each result is written inside its span
    for span, event in ((failed, "webhook_retry"), (delivered, "webhook_delivered")):
        [line] = json_logs.event(event)
        assert (line["trace_id"], line["span_id"]) == span_ids(span)
        assert line["event.name"] == event.replace("_", ".")
