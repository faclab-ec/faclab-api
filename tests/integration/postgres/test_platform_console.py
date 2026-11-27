"""The platform console on PostgreSQL (S8.5): an operator logs in with a token
that has no tenant, creates, lists and suspends companies and changes their
plan, every action leaves its entry in the company's audit log, and the token
only works under /api/platform."""

from uuid import uuid4

import jwt
import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from config import config
from src.audit.infra.models import AuditLogModel
from src.auth.domain.entities import Role
from src.auth.infra.models import AuthSessionModel, UserModel
from src.auth.infra.password_hasher import BcryptPasswordHasher
from src.platform_console.infra.models import PlatformOperatorModel
from src.subscriptions.infra.guard import subscription_access
from src.subscriptions.infra.models import PlanModel
from src.tenancy.infra.models import MembershipModel
from tests.integration.postgres.api import Api
from tests.integration.postgres.tenants import OTHER_TENANT_RUC

LOGIN = "/api/platform/auth/login"
TENANTS = "/api/platform/tenants"
PASSWORD = "operator-pass-1"
NEW_COMPANY = {
    "ruc": OTHER_TENANT_RUC,
    "legalName": "Ferretería El Clavo S.A.",
    "adminUsername": "clavo-admin",
    "adminEmail": "admin@clavo.test",
    "adminFullName": "Ana Clavo",
}


def _user(engine: Engine, username: str, *, operator: bool, active: bool = True):
    with Session(bind=engine) as session:
        user = UserModel(
            username=username,
            email=f"{username}@faclab.test",
            password_hash=BcryptPasswordHasher().hash(PASSWORD),
            is_active=True,
            full_name=username.title(),
        )
        session.add(user)
        session.flush()
        if operator:
            session.add(PlatformOperatorModel(user_id=user.id, is_active=active))
        session.commit()


def _login(client, username: str = "ops", password: str = PASSWORD):
    return client.post(LOGIN, json={"username": username, "password": password})


@pytest.fixture
def operator(client, pg_engine) -> dict[str, str]:
    _user(pg_engine, "ops", operator=True)
    response = _login(client)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['accessToken']}"}


@pytest.fixture
def console(client, operator) -> Api:
    return Api(client, operator)


def _audit(engine: Engine, tenant_id, action: str) -> list[AuditLogModel]:
    with Session(bind=engine) as session:
        # The fixture's engine is the superuser, which row-level security ignores
        return list(
            session.scalars(
                select(AuditLogModel)
                .where(AuditLogModel.tenant_id == tenant_id)
                .where(AuditLogModel.action == action)
            )
        )


def _code(response) -> str:
    return response.json()["errors"][0]["code"]


# Login


def test_an_operator_logs_in_with_a_token_without_tenant(client, pg_engine):
    _user(pg_engine, "ops", operator=True)

    response = _login(client)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["displayName"] == "Ops"
    claims = jwt.decode(data["accessToken"], options={"verify_signature": False})
    assert claims["typ"] == "platform"
    assert "tid" not in claims and "role" not in claims
    # Only this service: faclab-invoicing doesn't accept it
    assert claims["aud"] == config.JWT_AUDIENCE


@pytest.mark.parametrize(
    "username, password",
    [("ops", "wrong-password"), ("nobody", PASSWORD), ("regular", PASSWORD)],
)
def test_a_wrong_password_a_stranger_and_a_non_operator_fail_alike(
    client, pg_engine, username, password
):
    _user(pg_engine, "ops", operator=True)
    _user(pg_engine, "regular", operator=False)

    response = _login(client, username, password)

    assert (response.status_code, _code(response)) == (401, "INVALID_CREDENTIALS")


def test_a_deactivated_operator_cannot_log_in_nor_use_its_token(
    client, pg_engine, console, operator
):
    assert client.get(TENANTS, headers=operator).status_code == 200
    with Session(bind=pg_engine) as session:
        session.execute(update(PlatformOperatorModel).values(is_active=False))
        session.commit()

    assert client.get(TENANTS, headers=operator).status_code == 403
    assert _login(client).status_code == 401


# An operator's identity can't be taken from a company (S9.3)


def _member_of(engine: Engine, username: str, tenant_id) -> int:
    with Session(bind=engine) as session:
        user = session.scalars(
            select(UserModel).where(UserModel.username == username)
        ).one()
        session.add(
            MembershipModel(
                tenant_id=tenant_id,
                user_id=user.id,
                role=int(Role.VIEWER),
                active=True,
            )
        )
        session.commit()
        return user.id


def test_a_company_admin_cannot_reset_nor_rename_an_operator(
    client, pg_engine, tenant, admin
):
    """The operator works in one company only, so `USER_IN_OTHER_TENANTS`
    doesn't stop its admin; the console reaches every company"""
    _user(pg_engine, "ops", operator=True)
    user_id = _member_of(pg_engine, "ops", tenant)

    reset = client.post(
        f"/api/admin/users/{user_id}/reset-password",
        json={"newPassword": "taken-over-1"},
        headers=admin,
    )
    rename = client.put(
        f"/api/admin/users/{user_id}/profile",
        json={"fullName": "Not Ops"},
        headers=admin,
    )

    assert (reset.status_code, _code(reset)) == (409, "USER_IS_PLATFORM_OPERATOR")
    assert (rename.status_code, _code(rename)) == (409, "USER_IS_PLATFORM_OPERATOR")
    assert _login(client, "ops", "taken-over-1").status_code == 401
    assert _login(client).status_code == 200


def test_a_temporary_password_does_not_open_the_console(client, pg_engine):
    _user(pg_engine, "ops", operator=True)
    with Session(bind=pg_engine) as session:
        session.execute(update(UserModel).values(must_change_password=True))
        session.commit()

    response = _login(client)

    assert (response.status_code, _code(response)) == (403, "PASSWORD_CHANGE_REQUIRED")


# The token only works under /api/platform


def test_a_platform_token_is_refused_on_the_companies_api(client, operator):
    response = client.get("/api/admin/branches", headers=operator)

    assert (response.status_code, _code(response)) == (403, "PLATFORM_NOT_ALLOWED")


def test_a_company_token_is_refused_on_the_console(client, admin):
    assert client.get(TENANTS, headers=admin).status_code == 403
    assert client.get(TENANTS).status_code == 403


def test_a_disabled_console_answers_503(client, operator, monkeypatch):
    monkeypatch.setattr(config, "PLATFORM_CONSOLE_ENABLED", False)

    response = client.get(TENANTS, headers=operator)

    assert (response.status_code, _code(response)) == (503, "PLATFORM_CONSOLE_DISABLED")
    assert _login(client).status_code == 503


# Companies


def test_the_operator_creates_a_company_with_its_first_admin(
    client, console, pg_engine
):
    created = console.post(TENANTS, NEW_COMPANY)

    assert created["tenantCreated"] and created["userCreated"]
    password = created["adminPassword"]
    # The company's admin logs in with it, and must change it
    login = client.post(
        "/api/auth/login", json={"username": "clavo-admin", "password": password}
    )
    assert login.status_code == 200, login.text
    access = login.json()["data"]["accessToken"]
    admin = {"Authorization": f"Bearer {access}"}
    assert client.get("/api/admin/branches", headers=admin).status_code == 403
    # Its structure and its plan are there
    me = client.get("/api/auth/me", headers=admin).json()["data"]
    assert me["tenant"]["ruc"] == OTHER_TENANT_RUC
    # A repeated request completes nothing new and gives no password
    again = console.post(TENANTS, NEW_COMPANY)
    assert not again["tenantCreated"] and again["adminPassword"] is None
    entries = _audit(pg_engine, created["tenantId"], "tenant.provisioned")
    assert [e.actor_name for e in entries] == ["Ops", "Ops"]
    assert entries[0].source == "task"
    assert "adminPassword" not in str(entries[0].after)


def test_the_operator_lists_filters_and_reads_a_company(console, pg_engine, tenant):
    other = console.post(TENANTS, NEW_COMPANY)["tenantId"]

    everything = console.get(TENANTS)
    assert everything["total"] == 2
    found = console.get(TENANTS, params={"q": "Clavo"})
    assert [item["id"] for item in found["items"]] == [other]
    assert console.get(TENANTS, params={"status": "suspended"})["total"] == 0

    detail = console.get(f"{TENANTS}/{other}")
    assert detail["ruc"] == OTHER_TENANT_RUC
    assert detail["activeBranches"] == 1 and detail["activeUsers"] == 1
    assert detail["subscription"]["plan"]["code"] == "ilimitado"
    assert detail["invoicing"]["pendingInvoices"] == 0
    assert console.error("GET", f"{TENANTS}/{uuid4()}", 404)["code"] == "NOT_FOUND"


def test_suspending_a_company_closes_its_door_and_activating_opens_it(
    client, console, pg_engine
):
    created = console.post(TENANTS, NEW_COMPANY)
    tenant_id = created["tenantId"]
    credentials = {"username": "clavo-admin", "password": created["adminPassword"]}
    assert client.post("/api/auth/login", json=credentials).status_code == 200

    result = console.post(f"{TENANTS}/{tenant_id}/suspend", {"reason": "falta de pago"})

    assert result["status"] == "suspended" and result["revokedSessions"] == 1
    refused = client.post("/api/auth/login", json=credentials)
    assert (refused.status_code, _code(refused)) == (403, "NO_ACTIVE_TENANT")
    with Session(bind=pg_engine) as session:
        assert session.scalar(
            select(AuthSessionModel.revoked_at).where(
                AuthSessionModel.tenant_id == tenant_id
            )
        )
    twice = console.error("POST", f"{TENANTS}/{tenant_id}/suspend", 409, json={})
    assert twice["code"] == "TENANT_ALREADY_SUSPENDED"

    assert console.post(f"{TENANTS}/{tenant_id}/activate", {})["status"] == "active"
    assert client.post("/api/auth/login", json=credentials).status_code == 200
    suspended = _audit(pg_engine, tenant_id, "tenant.suspended")
    assert (suspended[0].after or {})["reason"] == "falta de pago"
    assert suspended[0].actor_name == "Ops"
    assert len(_audit(pg_engine, tenant_id, "tenant.activated")) == 1


def test_the_operator_starts_and_takes_back_the_offboarding_of_a_company(
    client, console, pg_engine
):
    created = console.post(TENANTS, NEW_COMPANY)
    tenant_id = created["tenantId"]
    credentials = {"username": "clavo-admin", "password": created["adminPassword"]}

    started = console.post(f"{TENANTS}/{tenant_id}/offboarding", {})

    # Read-only with a grace period, and the company still signs in to export
    assert started["status"] == "active"
    assert started["offboardingStartedAt"] and started["graceEndsAt"]
    assert started["retentionEndsAt"] and started["anonymizedAt"] is None
    assert client.post("/api/auth/login", json=credentials).status_code == 200
    again = console.error("POST", f"{TENANTS}/{tenant_id}/offboarding", 409, json={})
    assert again["code"] == "OFFBOARDING_ALREADY_STARTED"
    entry = _audit(pg_engine, tenant_id, "tenant.offboarding_started")
    assert len(entry) == 1 and entry[0].actor_name == "Ops"

    back = console.delete(f"{TENANTS}/{tenant_id}/offboarding")

    assert back["offboardingStartedAt"] is None and back["graceEndsAt"] is None
    assert len(_audit(pg_engine, tenant_id, "tenant.offboarding_cancelled")) == 1
    nothing = console.error("DELETE", f"{TENANTS}/{tenant_id}/offboarding", 409)
    assert nothing["code"] == "OFFBOARDING_NOT_STARTED"


def test_the_operator_changes_the_plan_and_the_status(console, pg_engine):
    tenant_id = console.post(TENANTS, NEW_COMPANY)["tenantId"]
    with Session(bind=pg_engine) as session:
        session.add(PlanModel(code="basico", name="Básico", max_branches=1))
        session.commit()

    result = console.put(
        f"{TENANTS}/{tenant_id}/subscription",
        {"planCode": "basico", "status": "suspended"},
    )

    assert result["plan"]["code"] == "basico"
    assert result["status"] == "suspended" and result["readOnly"] is True
    assert {p["code"] for p in console.get("/api/platform/plans")} == {
        "ilimitado",
        "basico",
    }
    entry = _audit(pg_engine, tenant_id, "subscription.changed")[0]
    assert (entry.after or {})["plan"] == "basico" and entry.actor_name == "Ops"
    subscription_access().forget()
