"""`CachedIntegrationAccess`: what an integration's token is worth now. The
client's state is cached at most INTEGRATION_STATUS_CACHE_SECONDS (60 or less),
so a revocation reaches every process within that time."""

from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from config import config
from src.auth.app.services.token_service import ClientTokenClaims
from src.auth.domain.scopes import Scope
from src.integrations.domain.credentials import IntegrationEnvironment
from src.integrations.infra.access import CachedIntegrationAccess
from src.integrations.infra.models import (
    ClientSecretModel,
    IntegrationClientDirectoryModel,
    IntegrationClientModel,
    IntegrationUsageModel,
)
from src.organization.infra.models import BranchModel
from tests.conftest import TEST_TENANT_ID
from tests.integrations_kit import Kit
from tests.sqlite import sqlite_session

TTL = 30


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


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
    db.add_all(
        [
            BranchModel(id=1, establishment_code="001", name="Matriz"),
            BranchModel(id=2, establishment_code="002", name="Norte"),
        ]
    )
    db.commit()
    yield db
    db.close()


@pytest.fixture
def kit(session) -> Kit:
    return Kit(session)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def access(session, clock) -> CachedIntegrationAccess:
    # The same in-memory database: SQLite keeps one connection per thread
    factory = sessionmaker(bind=session.get_bind())
    return CachedIntegrationAccess(
        lambda: factory,
        environment=IntegrationEnvironment.SANDBOX,
        ttl_seconds=TTL,
        clock=clock,
    )


def _claims(created: dict, **overrides) -> ClientTokenClaims:
    values = {
        "public_id": created["client_id"],
        "tid": TEST_TENANT_ID,
        "secret_id": created["secrets"][0]["id"],
        "scopes": frozenset({Scope.STOCK_READ, Scope.SALES_WRITE}),
        "iat": 0,
        "exp": 0,
        "iss": "faclab-core",
        "bids": None,
    }
    values.update(overrides)
    return ClientTokenClaims(**values)


def _created(kit, session, **values) -> dict:
    created = kit.create(**{"scopes": [Scope.STOCK_READ, Scope.SALES_WRITE], **values})
    session.commit()
    return created


def test_the_status_cache_never_passes_a_minute():
    assert 0 <= config.INTEGRATION_STATUS_CACHE_SECONDS <= 60


def test_an_active_client_gets_its_principal(kit, session, access):
    created = _created(kit, session, branch_ids=[1])

    principal = access.principal(_claims(created, bids=frozenset({1})), "203.0.113.7")

    assert principal is not None
    assert principal.client_id == created["id"]
    assert principal.name == "Tienda web"
    assert principal.tenant_id == TEST_TENANT_ID
    assert principal.scopes == {Scope.STOCK_READ, Scope.SALES_WRITE}
    assert principal.branch_ids == {1}


def test_a_revoked_client_stops_working_once_the_cache_expires(
    kit, session, access, clock
):
    created = _created(kit, session)
    claims = _claims(created)
    assert access.principal(claims, None) is not None

    kit.revoke(created["id"])
    session.commit()

    # Within the cache it is still the state read before
    clock.now += TTL - 1
    assert access.principal(claims, None) is not None
    # After it, never: at most INTEGRATION_STATUS_CACHE_SECONDS
    clock.now += 2
    assert access.principal(claims, None) is None


def test_a_revoked_secret_stops_its_tokens(kit, session, access, clock):
    created = _created(kit, session)
    second = kit.rotate(created["id"])
    session.commit()
    first_claims = _claims(created)
    second_claims = _claims(created, secret_id=second["id"])

    kit.revoke_secret(created["id"], created["secrets"][0]["id"])
    session.commit()

    assert access.principal(first_claims, None) is None
    assert access.principal(second_claims, None) is not None


def test_an_expired_secret_stops_its_tokens(kit, session, access):
    created = _created(kit, session)
    secret = session.get(ClientSecretModel, created["secrets"][0]["id"])
    assert secret is not None
    secret.expires_at = datetime.now() - timedelta(seconds=1)
    session.commit()

    assert access.principal(_claims(created), None) is None


def test_scopes_and_branches_taken_away_narrow_the_token(kit, session, access):
    created = _created(kit, session)
    kit.update(created["id"], scopes=[Scope.STOCK_READ], branch_ids=[2])
    session.commit()

    principal = access.principal(_claims(created, bids=frozenset({1, 2})), None)

    assert principal is not None
    assert principal.scopes == {Scope.STOCK_READ}
    assert principal.branch_ids == {2}


def test_a_token_limited_to_branches_keeps_its_limit(kit, session, access):
    created = _created(kit, session)

    principal = access.principal(_claims(created, bids=frozenset({1})), None)

    assert principal is not None and principal.branch_ids == {1}


def test_an_address_outside_the_client_networks_is_refused(kit, session, access):
    created = _created(kit, session, allowed_ips=["10.0.0.0/8"])

    assert access.principal(_claims(created), "203.0.113.7") is None
    assert access.principal(_claims(created), "10.9.8.7") is not None


def test_a_client_of_another_environment_is_refused(kit, session, clock):
    created = _created(kit, session)
    factory = sessionmaker(bind=session.get_bind())
    production = CachedIntegrationAccess(
        lambda: factory,
        environment=IntegrationEnvironment.PRODUCTION,
        ttl_seconds=TTL,
        clock=clock,
    )

    assert production.principal(_claims(created), None) is None


def test_an_unknown_client_is_refused(kit, session, access):
    created = _created(kit, session)

    assert (
        access.principal(_claims(created, public_id="fl_test_000000000000"), None)
        is None
    )


def test_each_request_counts_in_the_usage_of_the_day(kit, session, access):
    created = _created(kit, session)
    principal = access.principal(_claims(created), None)
    assert principal is not None

    access.record_request(principal, 200, "203.0.113.7")
    access.record_request(principal, 403, "203.0.113.8")
    session.expire_all()

    usage = session.scalars(select(IntegrationUsageModel)).one()
    assert (usage.requests, usage.errors) == (2, 1)
    assert usage.last_ip == "203.0.113.8"
    client = session.get(IntegrationClientModel, created["id"])
    assert client is not None and client.last_used_at is not None


def test_the_usage_never_breaks_the_request(kit, session, access):
    created = _created(kit, session)
    principal = access.principal(_claims(created), None)
    assert principal is not None

    def broken():
        raise RuntimeError("database down")

    access._session_maker = broken  # noqa: SLF001

    access.record_request(principal, 200, None)


def test_the_tenant_of_a_client(kit, session, access):
    created = _created(kit, session)

    assert access.tenant_of(created["client_id"]) == TEST_TENANT_ID
    assert access.tenant_of("fl_test_000000000000") is None
