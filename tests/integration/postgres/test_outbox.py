"""Kafka outbox against PostgreSQL: a confirmed sale leaves a message for
faclab-invoicing in the same transaction, and the relay (as faclab_worker)
publishes it."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import config
from src.auth.domain.entities import Role
from src.shared.infra.database import worker_session_maker
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


class FakePublisher:
    def __init__(self):
        self.sent: list[tuple[str, dict, list]] = []

    def publish(self, topic, value, headers):
        self.sent.append((topic, value, headers))


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
        headers=cashier.headers,
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
