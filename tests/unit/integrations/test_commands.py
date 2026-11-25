"""The commands of the integration clients over SQLite: the real repositories,
a fake audit trail."""

from collections.abc import Iterator
from datetime import datetime, timedelta

import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.domain.scopes import Scope
from src.integrations.app.commands.token import TokenDenied, TokenGranted
from src.integrations.app.plan import IntegrationPlan
from src.integrations.app.queries.clients import (
    ListIntegrationClientsQuery,
    ListIntegrationClientsQueryHandler,
)
from src.integrations.app.settings import IntegrationSettings
from src.integrations.domain.credentials import IntegrationEnvironment, hash_secret
from src.integrations.domain.entities import IntegrationClientStatus
from src.integrations.domain.events import IntegrationClientRevoked
from src.integrations.domain.exceptions import (
    IntegrationBranchNotFoundError,
    IntegrationClientRevokedError,
    IntegrationSecretLimitReachedError,
    IntegrationSecretRevokedError,
    ScopeNotInPlanError,
)
from src.integrations.infra.models import (
    ClientSecretModel,
    IntegrationClientDirectoryModel,
    IntegrationClientModel,
    IntegrationUsageModel,
)
from src.organization.infra.models import BranchModel
from src.shared.app.audit import AuditAction
from src.shared.app.plans import PlanLimitReachedError, PlanResource
from src.tenancy.infra.models import TenantModel
from tests.conftest import TEST_TENANT_ID
from tests.integrations_kit import Kit
from tests.sqlite import sqlite_session


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    db = sqlite_session(
        [
            BranchModel,
            IntegrationClientModel,
            ClientSecretModel,
            IntegrationUsageModel,
            IntegrationClientDirectoryModel,
        ]
    )
    db.add_all([BranchModel(id=1, establishment_code="001", name="Matriz")])
    db.flush()
    yield db
    db.close()


@pytest.fixture
def kit(session) -> Kit:
    return Kit(session)


def test_creating_a_client_shows_its_secret_once_and_keeps_its_hash(kit, session):
    created = kit.create(scopes=[Scope.SALES_WRITE, Scope.STOCK_READ], branch_ids=[1])

    secret = created["client_secret"]
    assert created["client_id"].startswith("fl_test_")
    assert created["scopes"] == [Scope.SALES_WRITE, Scope.STOCK_READ]
    assert created["branch_ids"] == [1]
    stored = session.scalars(select(ClientSecretModel)).one()
    assert stored.secret_hash == hash_secret(secret)
    assert stored.prefix == secret[:6]
    # The directory knows its tenant
    directory = session.get(IntegrationClientDirectoryModel, created["client_id"])
    assert directory is not None and directory.tenant_id == TEST_TENANT_ID
    # Never shown again, never in the audit log
    detail = kit.detail(created["id"])
    assert "client_secret" not in detail
    assert secret not in repr(detail) and stored.secret_hash not in repr(detail)
    [entry] = kit.audit.entries
    assert entry.action is AuditAction.INTEGRATION_CREATED
    assert entry.resource_id == created["id"]
    assert secret not in repr(entry) and stored.secret_hash not in repr(entry)


def test_a_branch_of_another_tenant_is_not_found(kit):
    with pytest.raises(IntegrationBranchNotFoundError):
        kit.create(branch_ids=[1, 99])


def test_a_scope_outside_the_plan_is_refused(kit):
    class StockOnly(IntegrationPlan):
        def allowed_scopes(self):
            return frozenset({Scope.STOCK_READ})

    with pytest.raises(ScopeNotInPlanError):
        kit.create(plan=StockOnly(), scopes=[Scope.STOCK_READ, Scope.SALES_WRITE])


def test_updating_records_only_what_changed(kit):
    created = kit.create()

    updated = kit.update(
        created["id"],
        scopes=[Scope.STOCK_READ, Scope.SALES_READ],
        allowed_ips=["10.0.0.0/8"],
    )
    kit.update(
        created["id"],
        scopes=[Scope.STOCK_READ, Scope.SALES_READ],
        allowed_ips=["10.0.0.0/8"],
    )

    assert updated["allowed_ips"] == ["10.0.0.0/8"]
    assert kit.audit.actions == [
        AuditAction.INTEGRATION_CREATED,
        AuditAction.INTEGRATION_UPDATED,
    ]
    entry = kit.audit.entries[1]
    assert set(entry.after or {}) == {"scopes", "allowed_ips"}


def test_rotation_keeps_at_most_two_active_secrets(kit):
    created = kit.create()

    second = kit.rotate(created["id"])
    with pytest.raises(IntegrationSecretLimitReachedError):
        kit.rotate(created["id"])

    assert second["client_secret"] != created["client_secret"]
    assert [s["is_active"] for s in kit.detail(created["id"])["secrets"]] == [
        True,
        True,
    ]


def test_rotating_with_an_expiry_makes_the_current_secrets_expire(kit):
    created = kit.create()

    kit.rotate(created["id"], previous_expires_in_days=7)
    first, second = kit.detail(created["id"])["secrets"]

    assert first["expires_at"] is not None
    assert first["expires_at"] - datetime.now() > timedelta(days=6)
    assert second["expires_at"] is None
    # Expiring now frees the place at once
    kit.rotate(created["id"], previous_expires_in_days=0)
    assert [s["is_active"] for s in kit.detail(created["id"])["secrets"]] == [
        False,
        False,
        True,
    ]


def test_revoking_a_secret(kit):
    created = kit.create()
    secret_id = created["secrets"][0]["id"]

    revoked = kit.revoke_secret(created["id"], secret_id)

    assert revoked["is_active"] is False
    with pytest.raises(IntegrationSecretRevokedError):
        kit.revoke_secret(created["id"], secret_id)
    assert kit.audit.actions[-1] is AuditAction.INTEGRATION_SECRET_REVOKED


def test_revoking_a_client_revokes_its_secrets(kit):
    created = kit.create()
    kit.rotate(created["id"])

    revoked = kit.revoke(created["id"])

    assert revoked["status"] == "REVOKED"
    assert all(not s["is_active"] for s in revoked["secrets"])
    with pytest.raises(IntegrationClientRevokedError):
        kit.revoke(created["id"])
    with pytest.raises(IntegrationClientRevokedError):
        kit.rotate(created["id"])
    with pytest.raises(IntegrationClientRevokedError):
        kit.update(created["id"])
    # Its webhook endpoints stop with it (S6.4), in the same transaction
    [call] = kit.publisher.publish.call_args_list
    assert call.args[0] == IntegrationClientRevoked(
        aggregate_id=created["id"],
        client_id=created["id"],
        event_id=call.args[0].event_id,
        occurred_at=call.args[0].occurred_at,
        tenant_id=call.args[0].tenant_id,
    )
    assert call.kwargs["session"] is kit.session


def test_listing_shows_the_clients_with_their_secrets(kit):
    first = kit.create(name="Uno")
    second = kit.create(name="Dos")
    kit.revoke(second["id"])

    listing = ListIntegrationClientsQueryHandler(kit.clients, kit.secrets).handle(
        ListIntegrationClientsQuery(limit=10, offset=0)
    )
    active = ListIntegrationClientsQueryHandler(kit.clients, kit.secrets).handle(
        ListIntegrationClientsQuery(
            status=IntegrationClientStatus.ACTIVE, limit=10, offset=0
        )
    )

    assert [c["name"] for c in listing["items"]] == ["Uno", "Dos"]
    assert listing["total"] == 2
    assert [c["id"] for c in active["items"]] == [first["id"]]
    assert all(len(c["secrets"]) == 1 for c in listing["items"])


def test_a_token_with_the_client_scopes(kit, session):
    created = kit.create(scopes=[Scope.STOCK_READ, Scope.SALES_WRITE], branch_ids=[1])

    result = kit.token(created["client_id"], created["client_secret"])

    assert isinstance(result, TokenGranted)
    assert result.scope == "sales:write stock:read"
    claims = jwt.decode(result.access_token, options={"verify_signature": False})
    assert claims["azp"] == created["client_id"]
    assert claims["tid"] == str(TEST_TENANT_ID)
    assert claims["bids"] == [1]
    assert claims["cred"] == created["secrets"][0]["id"]
    detail = kit.detail(created["id"])
    assert detail["last_used_at"] is not None
    assert detail["secrets"][0]["last_used_at"] is not None
    [day] = kit.usage_days(created["id"])
    assert (day["token_requests"], day["token_failures"]) == (1, 0)
    assert day["last_ip"] == "203.0.113.7"


def test_a_token_with_fewer_scopes(kit):
    created = kit.create(scopes=[Scope.STOCK_READ, Scope.SALES_WRITE])

    result = kit.token(created["client_id"], created["client_secret"], "stock:read")

    assert isinstance(result, TokenGranted)
    assert result.scope == "stock:read"


@pytest.mark.parametrize("scope", ["sales:write", "users:manage", "stock:read nope"])
def test_a_scope_the_client_lacks_is_invalid_scope(kit, scope):
    created = kit.create()

    result = kit.token(created["client_id"], created["client_secret"], scope)

    assert result == TokenDenied(
        "invalid_scope",
        "scope not granted",
        "the requested scope is unknown or not granted to the client",
    )


def _denied(kit, created, **overrides) -> TokenDenied:
    values = {"public_id": created["client_id"], "secret": created["client_secret"]}
    values.update(overrides)
    result = kit.token(**values)
    assert isinstance(result, TokenDenied)
    assert result.error == "invalid_client"
    return result


def test_a_wrong_secret_is_refused_and_counted(kit):
    created = kit.create()

    assert _denied(kit, created, secret="wrong").reason == "wrong secret"
    [day] = kit.usage_days(created["id"])
    assert (day["token_requests"], day["token_failures"]) == (0, 1)


def test_an_unknown_client_is_refused(kit):
    created = kit.create()

    result = _denied(kit, created, public_id="fl_test_000000000000")

    assert result.reason == "unknown client"


def test_a_revoked_client_or_secret_gets_no_token(kit):
    created = kit.create()
    second = kit.rotate(created["id"])
    kit.revoke_secret(created["id"], created["secrets"][0]["id"])

    assert _denied(kit, created).reason == "secret revoked or expired"
    assert isinstance(
        kit.token(created["client_id"], second["client_secret"]), TokenGranted
    )

    kit.revoke(created["id"])
    assert _denied(kit, created, secret=second["client_secret"]).reason == (
        "client revoked"
    )


def test_a_client_of_another_environment_gets_no_token(kit):
    created = kit.create()
    production = IntegrationSettings(environment=IntegrationEnvironment.PRODUCTION)

    assert _denied(kit, created, settings=production).reason == (
        "client of the sandbox environment"
    )


def test_an_address_outside_the_client_networks_gets_no_token(kit):
    created = kit.create(allowed_ips=["10.0.0.0/8"])

    assert _denied(kit, created).reason == "address not allowed"
    assert isinstance(
        kit.token(created["client_id"], created["client_secret"], ip="10.1.2.3"),
        TokenGranted,
    )


def test_a_suspended_tenant_gets_no_token(kit, session):
    created = kit.create()
    session.get(TenantModel, TEST_TENANT_ID).status = "suspended"  # type: ignore[union-attr]
    session.flush()

    assert _denied(kit, created).reason == "tenant not active"


def test_a_client_beyond_the_plan_is_refused(kit, session):
    kit.limits.full = {PlanResource.INTEGRATION_CLIENTS}

    with pytest.raises(PlanLimitReachedError):
        kit.create()
    assert session.scalars(select(IntegrationClientModel)).all() == []
