"""The webhook endpoints' commands and queries over SQLite (S6.4): the real
repositories, a fake audit trail and a resolver without DNS."""

from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.domain.exceptions import InsufficientScopeError
from src.auth.domain.scopes import Scope
from src.integrations.domain.exceptions import IntegrationClientRevokedError
from src.shared.app.audit import AuditAction
from src.shared.domain.exceptions import NotFoundError
from src.webhooks.domain.entities import (
    MAX_ENDPOINTS_PER_TENANT,
    DisabledReason,
    WebhookDeliveryStatus,
)
from src.webhooks.domain.exceptions import (
    WebhookDeliveryPendingError,
    WebhookEndpointDisabledError,
    WebhookEndpointLimitReachedError,
    WebhookOwnerNotFoundError,
    WebhookOwnerRequiredError,
    WebhookUrlNotAllowedError,
)
from src.webhooks.domain.signing import SECRET_PREFIX
from src.webhooks.domain.types import WebhookEventType
from src.webhooks.infra.models import (
    WebhookDeliveryModel,
    WebhookEndpointModel,
    WebhookMessageModel,
)
from tests.conftest import TEST_TENANT_ID
from tests.sqlite import sqlite_session
from tests.webhooks_kit import URL, WEBHOOK_MODELS, Kit

SALE = WebhookEventType.SALE_CONFIRMED
PRODUCT = WebhookEventType.PRODUCT_UPDATED


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    db = sqlite_session(WEBHOOK_MODELS)
    yield db
    db.close()


@pytest.fixture
def kit(session) -> Kit:
    return Kit(session)


def test_an_endpoint_is_created_with_a_secret_shown_only_by_its_hint(kit, session):
    created = kit.create(description="Tienda", event_types=[SALE, PRODUCT])

    assert created["url"] == URL
    assert created["event_types"] == [PRODUCT, SALE]
    assert created["status"] == "active"
    assert created["secret_hint"].startswith(SECRET_PREFIX)
    assert "secret" not in created and "secret_ciphertext" not in created
    stored = session.scalars(select(WebhookEndpointModel)).one()
    assert stored.tenant_id == TEST_TENANT_ID
    # Encrypted in the table; the query opens it
    secret = kit.secret(created["id"])["secret"]
    assert secret.startswith(created["secret_hint"])
    assert secret not in stored.secret_ciphertext
    assert kit.box.open(stored.secret_ciphertext) == secret
    [entry] = kit.audit.entries
    assert entry.action is AuditAction.WEBHOOK_ENDPOINT_CREATED
    assert entry.after == {
        "url": URL,
        "event_types": [PRODUCT, SALE],
        "description": "Tienda",
        "exclude_own_changes": False,
        "integration_client_id": None,
    }


def test_the_audit_log_keeps_the_url_without_its_query(kit):
    kit.create(url=URL + "?token=s3cr3t")

    assert kit.audit.entries[0].after["url"] == URL + "?…"


def test_a_url_the_server_may_not_call_is_refused_before_anything_is_written(
    kit, session
):
    with pytest.raises(WebhookUrlNotAllowedError):
        kit.create(url="https://interno.tienda.example/hooks")
    with pytest.raises(WebhookUrlNotAllowedError):
        kit.create(url="http://hooks.tienda.example/hooks")

    assert session.scalars(select(WebhookEndpointModel)).all() == []
    assert kit.audit.entries == []


def test_a_client_s_endpoint_needs_the_read_scope_of_each_event(kit):
    client = kit.client(scopes=[Scope.WEBHOOKS_MANAGE, Scope.SALES_READ])

    with pytest.raises(InsufficientScopeError, match="products:read"):
        kit.create(client_id=client.require_id(), event_types=[SALE, PRODUCT])

    created = kit.create(client_id=client.require_id(), exclude_own_changes=True)
    assert created["integration_client_id"] == client.id
    assert created["exclude_own_changes"] is True


def test_exclude_own_changes_needs_a_client_that_exists_and_is_active(kit):
    with pytest.raises(WebhookOwnerRequiredError):
        kit.create(exclude_own_changes=True)
    with pytest.raises(WebhookOwnerNotFoundError):
        kit.create(client_id=999)

    client = kit.client()
    client.revoke(datetime.now())
    kit.clients.update(client)
    with pytest.raises(IntegrationClientRevokedError):
        kit.create(client_id=client.require_id())


def test_a_company_has_at_most_twenty_endpoints(kit):
    for _ in range(MAX_ENDPOINTS_PER_TENANT):
        kit.create()

    with pytest.raises(WebhookEndpointLimitReachedError):
        kit.create()


def test_a_client_only_sees_and_changes_its_own_endpoints(kit):
    mine, other = kit.client(name="Tienda"), kit.client(name="Bodega")
    own = kit.create(client_id=mine.require_id())
    theirs = kit.create(client_id=other.require_id())
    company = kit.create()

    listed = kit.list(as_client_id=mine.require_id())
    assert [item["id"] for item in listed["items"]] == [own["id"]]
    assert listed["total"] == 1
    assert kit.list()["total"] == 3
    for endpoint_id in (theirs["id"], company["id"]):
        with pytest.raises(NotFoundError):
            kit.get(endpoint_id, as_client_id=mine.require_id())
        with pytest.raises(NotFoundError):
            kit.secret(endpoint_id, as_client_id=mine.require_id())
        with pytest.raises(NotFoundError):
            kit.update(endpoint_id, as_client_id=mine.require_id())
        with pytest.raises(NotFoundError):
            kit.delete(endpoint_id, as_client_id=mine.require_id())


def test_an_update_checks_the_url_again_and_audits_only_what_changed(kit):
    created = kit.create()

    with pytest.raises(WebhookUrlNotAllowedError):
        kit.update(created["id"], url="https://10.0.0.5/hooks")

    kit.update(created["id"])
    assert kit.audit.actions == [AuditAction.WEBHOOK_ENDPOINT_CREATED]

    updated = kit.update(
        created["id"],
        url="https://otro.tienda.example/hooks",
        event_types=[SALE, PRODUCT],
    )
    assert updated["url"] == "https://otro.tienda.example/hooks"
    entry = kit.audit.entries[-1]
    assert entry.action is AuditAction.WEBHOOK_ENDPOINT_UPDATED
    assert entry.before == {"url": URL, "event_types": [SALE]}
    assert entry.after == {
        "url": "https://otro.tienda.example/hooks",
        "event_types": [PRODUCT, SALE],
    }


def test_disabling_and_enabling_an_endpoint(kit):
    created = kit.create()

    disabled = kit.disable(created["id"])
    assert (disabled["status"], disabled["disabled_reason"]) == (
        "disabled",
        DisabledReason.MANUAL,
    )
    with pytest.raises(WebhookEndpointDisabledError):
        kit.send_test(created["id"])

    enabled = kit.enable(created["id"])
    assert (enabled["status"], enabled["disabled_reason"]) == ("active", None)
    assert kit.audit.actions[1:] == [
        AuditAction.WEBHOOK_ENDPOINT_DISABLED,
        AuditAction.WEBHOOK_ENDPOINT_ENABLED,
    ]
    # Enabling an active one changes nothing
    kit.enable(created["id"])
    assert len(kit.audit.entries) == 3


def test_the_worker_disables_a_failing_endpoint_once(kit):
    created = kit.create()

    disabled = kit.disable_failing(created["id"])

    assert disabled is not None
    assert disabled["disabled_reason"] == DisabledReason.FAILING
    assert kit.disable_failing(created["id"]) is None
    assert kit.audit.entries[-1].after == {
        "status": "disabled",
        "disabled_reason": DisabledReason.FAILING,
    }


def test_revoking_a_client_disables_its_endpoints_and_they_stay_so(kit):
    client = kit.client()
    created = kit.create(client_id=client.require_id())
    company = kit.create()

    assert kit.disable_of_client(client.require_id()) == 1

    assert kit.get(created["id"])["disabled_reason"] == DisabledReason.CLIENT_REVOKED
    assert kit.get(company["id"])["status"] == "active"
    client.revoke(datetime.now())
    kit.clients.update(client)
    with pytest.raises(IntegrationClientRevokedError):
        kit.enable(created["id"])


def test_a_rotation_keeps_the_previous_secret_for_a_while(kit):
    created = kit.create()
    first = kit.secret(created["id"])["secret"]

    rotated = kit.rotate(created["id"], hours=24)

    secrets = kit.secret(created["id"])
    assert secrets["secret"] != first
    assert secrets["previous_secret"] == first
    assert secrets["previous_expires_at"] > datetime.now() + timedelta(hours=23)
    assert rotated["secret_hint"] == secrets["secret"][:10]
    entry = kit.audit.entries[-1]
    assert entry.action is AuditAction.WEBHOOK_ENDPOINT_SECRET_ROTATED
    assert set(entry.after or {}) == {"previous_expires_at"}

    kit.rotate(created["id"], hours=0)
    assert kit.secret(created["id"])["previous_secret"] is None


def test_a_test_event_goes_to_that_endpoint_only_and_is_listed(kit, session):
    created = kit.create(event_types=[PRODUCT])
    other = kit.create(event_types=[PRODUCT])

    delivery = kit.send_test(created["id"])

    assert delivery["event_type"] == "webhook.test"
    assert delivery["status"] == WebhookDeliveryStatus.PENDING
    assert delivery["message_id"].startswith("msg_")
    message = session.scalars(select(WebhookMessageModel)).one()
    assert message.payload["type"] == "webhook.test"
    assert message.payload["data"]["endpointId"] == created["id"]
    assert message.payload["tenantId"] == str(TEST_TENANT_ID)
    history = kit.history(created["id"])
    assert [item["id"] for item in history["items"]] == [delivery["id"]]
    assert kit.history(other["id"])["total"] == 0


def test_only_a_delivered_or_failed_delivery_is_sent_again(kit, session):
    created = kit.create()
    delivery = kit.send_test(created["id"])

    with pytest.raises(WebhookDeliveryPendingError):
        kit.retry(created["id"], delivery["id"])

    row = session.get(WebhookDeliveryModel, delivery["id"])
    assert row is not None
    row.status, row.attempts = "failed", 9
    session.flush()
    retried = kit.retry(created["id"], delivery["id"])
    assert (retried["status"], retried["attempts"]) == ("pending", 0)
    assert retried["retried_at"] is not None
    # Of another endpoint: not found
    other = kit.create()
    with pytest.raises(NotFoundError):
        kit.retry(other["id"], delivery["id"])


def test_the_history_shows_the_retention_newest_first(kit, session):
    created = kit.create()
    old = kit.send_test(created["id"])
    new = kit.send_test(created["id"])
    row = session.get(WebhookDeliveryModel, old["id"])
    assert row is not None
    row.created_at = datetime.now() - timedelta(days=31)
    session.flush()

    history = kit.history(created["id"])

    assert [item["id"] for item in history["items"]] == [new["id"]]
    assert kit.history(created["id"], event_type="sale.confirmed")["total"] == 0


def test_deleting_an_endpoint_deletes_its_deliveries(kit, session):
    created = kit.create()
    kit.send_test(created["id"])

    kit.delete(created["id"])

    assert session.scalars(select(WebhookEndpointModel)).all() == []
    assert session.scalars(select(WebhookDeliveryModel)).all() == []
    assert kit.audit.entries[-1].action is AuditAction.WEBHOOK_ENDPOINT_DELETED
