"""Enqueuing the webhooks (S6.4): a message per event and a delivery per
endpoint that wants it, over SQLite."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.domain.scopes import Scope
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.tenant import tenant_scope
from src.webhooks.app.ports import WebhookSettings
from src.webhooks.domain.types import WebhookEventType
from src.webhooks.infra.models import WebhookDeliveryModel, WebhookMessageModel
from src.webhooks.infra.repositories import SqlAlchemyWebhookQueue
from tests.conftest import TEST_TENANT_ID
from tests.sqlite import sqlite_session
from tests.webhooks_kit import WEBHOOK_MODELS, Kit

SALE = WebhookEventType.SALE_CONFIRMED
PRODUCT = WebhookEventType.PRODUCT_UPDATED
DATA = {"saleId": 1}


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    db = sqlite_session(WEBHOOK_MODELS)
    yield db
    db.close()


@pytest.fixture
def kit(session) -> Kit:
    return Kit(session)


def _deliveries(session: Session) -> list[tuple[str, int]]:
    rows = session.execute(
        select(WebhookMessageModel.event_type, WebhookDeliveryModel.endpoint_id)
        .join(WebhookMessageModel)
        .order_by(WebhookDeliveryModel.id)
    )
    return [tuple(row) for row in rows]


def test_nothing_is_written_while_nobody_subscribes(kit, session):
    kit.create(event_types=[PRODUCT])

    assert not kit.outbox.subscribed(SALE)
    assert kit.outbox.enqueue(SALE, DATA, branch_id=12) == []
    assert session.scalars(select(WebhookMessageModel)).all() == []


def test_a_message_goes_once_to_every_endpoint_that_wants_it(kit, session):
    first = kit.create(event_types=[SALE])
    second = kit.create(event_types=[SALE, PRODUCT])
    kit.create(event_types=[PRODUCT])
    disabled = kit.create(event_types=[SALE])
    kit.disable(disabled["id"])
    occurred = datetime(2026, 11, 18, 15, 4, 5, 123000, tzinfo=UTC)

    ids = kit.outbox.enqueue(SALE, DATA, branch_id=12, occurred_at=occurred)

    assert len(ids) == 2
    assert _deliveries(session) == [
        ("sale.confirmed", first["id"]),
        ("sale.confirmed", second["id"]),
    ]
    message = session.scalars(select(WebhookMessageModel)).one()
    assert message.payload == {
        "id": message.public_id,
        "type": "sale.confirmed",
        "version": 1,
        "occurredAt": "2026-11-18T15:04:05.123Z",
        "tenantId": str(TEST_TENANT_ID),
        "originClientId": None,
        "data": DATA,
    }
    assert message.public_id.startswith("msg_")
    assert message.occurred_at == datetime(2026, 11, 18, 15, 4, 5, 123000)


def test_a_client_s_endpoint_gets_what_its_client_may_read(kit, session):
    limited = kit.client(scopes=[Scope.SALES_READ], branch_ids=[12], name="Tienda")
    endpoint = kit.create(client_id=limited.require_id(), event_types=[SALE])

    kit.outbox.enqueue(SALE, DATA, branch_id=15)
    kit.outbox.enqueue(SALE, DATA, branch_id=None)
    kit.outbox.enqueue(SALE, DATA, branch_id=12)

    assert _deliveries(session) == [("sale.confirmed", endpoint["id"])]


def test_narrowing_the_client_narrows_its_endpoints_in_the_next_transaction(
    kit, session
):
    client = kit.client(scopes=[Scope.SALES_READ])
    kit.create(client_id=client.require_id(), event_types=[SALE])
    session.commit()
    client.configure(client.name, frozenset({Scope.STOCK_READ}), None, None)
    kit.clients.update(client)
    session.commit()

    assert kit.outbox.enqueue(SALE, DATA, branch_id=12) == []


def test_a_revoked_client_s_endpoint_gets_nothing(kit, session):
    client = kit.client()
    kit.create(client_id=client.require_id(), event_types=[SALE])
    client.revoke(datetime.now())
    kit.clients.update(client)

    assert kit.outbox.enqueue(SALE, DATA, branch_id=12) == []


def test_exclude_own_changes_skips_what_its_client_did_and_says_who(kit, session):
    mine = kit.client(name="Tienda")
    other = kit.client(name="Bodega")
    excluding = kit.create(
        client_id=mine.require_id(), event_types=[SALE], exclude_own_changes=True
    )
    company = kit.create(event_types=[SALE])

    as_client = TenantContext(
        TEST_TENANT_ID, TenantSource.REQUEST, integration_id=mine.require_id()
    )
    with tenant_scope(as_client):
        kit.outbox.enqueue(SALE, DATA, branch_id=12)
    with tenant_scope(
        TenantContext(
            TEST_TENANT_ID, TenantSource.REQUEST, integration_id=other.require_id()
        )
    ):
        kit.outbox.enqueue(SALE, {"saleId": 2}, branch_id=12)

    assert _deliveries(session) == [
        ("sale.confirmed", company["id"]),
        ("sale.confirmed", excluding["id"]),
        ("sale.confirmed", company["id"]),
    ]
    first, second = session.scalars(
        select(WebhookMessageModel).order_by(WebhookMessageModel.id)
    ).all()
    assert first.payload["originClientId"] == mine.public_id
    assert first.origin_integration_id == mine.id
    assert second.payload["originClientId"] == other.public_id


def test_an_explicit_origin_wins_over_the_context(kit, session):
    client = kit.client()
    kit.create(
        client_id=client.require_id(), event_types=[SALE], exclude_own_changes=True
    )

    assert kit.outbox.enqueue(SALE, DATA, branch_id=12, origin=client.id) == []
    assert len(kit.outbox.enqueue(SALE, DATA, branch_id=12, origin=None)) == 1


def test_the_subscribers_are_read_once_per_transaction(kit, session):
    kit.create(event_types=[SALE])
    queue = SqlAlchemyWebhookQueue(session)

    first = queue.subscribers()
    assert SqlAlchemyWebhookQueue(session).subscribers() is first
    session.commit()
    assert SqlAlchemyWebhookQueue(session).subscribers() is not first


def test_with_webhooks_off_nothing_is_enqueued(session):
    kit = Kit(session, settings=WebhookSettings(enabled=False))
    kit.create(event_types=[SALE])

    assert not kit.outbox.subscribed(SALE)
    assert kit.outbox.enqueue(SALE, DATA, branch_id=12) == []
