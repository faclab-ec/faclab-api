"""Export of a company's data (S8.7, LOPDP) on PostgreSQL: the worker writes a
ZIP with a CSV per table of the company, every row of it and none of another's,
no secret, and the company can take it out even with a cancelled subscription."""

import csv
import io
import json
import zipfile
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from src.auth.domain.entities import Role
from src.data_protection.infra.purge import purge_files
from src.data_protection.infra.runner import export_file, run_exports
from src.shared.infra.database import worker_session_maker
from src.subscriptions.infra.guard import subscription_access
from src.subscriptions.infra.models import PlanModel, SubscriptionModel
from tests.integration.postgres.api import Api, make_customer
from tests.integration.postgres.support import issue_headers
from tests.integration.postgres.tenants import OTHER_TENANT_RUC, ensure_tenant


@pytest.fixture
def api(client, auth_headers) -> Api:
    return Api(client, auth_headers(Role.ADMIN, full_name="Ana Pérez"))


def _archive(api: Api, export_id: int) -> zipfile.ZipFile:
    response = api.client.get(
        f"/api/admin/data-exports/{export_id}/download", headers=api.headers
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(response.content))


def _rows(archive: zipfile.ZipFile, table: str) -> list[dict[str, str]]:
    with archive.open(f"{table}.csv") as raw:
        return list(csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig")))


def _export(api: Api) -> int:
    export_id = api.post("/api/admin/data-exports")["id"]
    assert run_exports(wait=True) == 1
    assert api.get(f"/api/admin/data-exports/{export_id}")["status"] == "READY"
    return export_id


def test_the_export_has_every_row_of_the_company_and_none_of_another(
    api, pg_engine, client
):
    mine = make_customer(api, 1, name="Constructora Andes")
    other_id = ensure_tenant(pg_engine, OTHER_TENANT_RUC)
    other = Api(client, issue_headers(pg_engine, tenant_id=other_id, username="otra"))
    theirs = make_customer(other, 2, name="Cliente de la otra")

    archive = _archive(api, _export(api))

    customers = _rows(archive, "customers")
    assert [row["tax_id"] for row in customers] == [mine["taxId"]]
    assert [row["name"] for row in customers] == ["Constructora Andes"]
    assert theirs["name"] not in "".join(
        archive.read(name).decode("utf-8-sig") for name in archive.namelist()
    )
    # Every tenant-scoped row of the company is there
    manifest = json.loads(archive.read("manifest.json"))
    with pg_engine.connect() as conn:
        for table, exported in manifest["tables"].items():
            if table in ("tenants", "users"):
                continue
            tenant_id = ensure_tenant(pg_engine)
            stored = conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),
                {"t": tenant_id},
            ).scalar_one()
            assert exported == stored, table
    assert manifest["tenant"]["id"] == str(ensure_tenant(pg_engine))
    # Its users, and only them (the other company's admin is not in it)
    usernames = {row["username"] for row in _rows(archive, "users")}
    assert "otra" not in usernames and usernames


def test_the_export_leaves_out_secrets_and_technical_tables(api):
    archive = _archive(api, _export(api))

    names = set(archive.namelist())
    assert {"tenants.csv", "users.csv", "memberships.csv", "manifest.json"} <= names
    for excluded in (
        "idempotency_keys",
        "outbox_messages",
        "auth_sessions",
        "dead_letters",
    ):
        assert f"{excluded}.csv" not in names
    assert "password_hash" not in _rows(archive, "users")[0]
    for name in names:
        header = archive.read(name).decode("utf-8-sig").splitlines()[0]
        assert "secret_hash" not in header
        assert "ciphertext" not in header
        assert "refresh_jti" not in header


def test_one_export_at_a_time_and_it_is_audited(api, pg_engine):
    first = api.post("/api/admin/data-exports")
    error = api.error("POST", "/api/admin/data-exports", 409)
    assert error["code"] == "EXPORT_IN_PROGRESS"
    assert (
        api.error("GET", f"/api/admin/data-exports/{first['id']}/download", 409)["code"]
        == "EXPORT_NOT_READY"
    )
    with pg_engine.connect() as conn:
        actions = conn.execute(
            text("SELECT action FROM audit_log WHERE action = 'data_export.requested'")
        ).all()
    assert len(actions) == 1


def test_only_the_admin_exports(client, auth_headers):
    for role in (Role.MANAGER, Role.OPERATOR, Role.VIEWER, Role.CASHIER):
        response = client.post("/api/admin/data-exports", headers=auth_headers(role))
        assert response.status_code == 403, role


def test_a_cancelled_company_can_still_take_its_data_out(api, pg_engine):
    tenant_id = ensure_tenant(pg_engine)
    with Session(bind=pg_engine) as session:
        plan_id = session.scalar(select(PlanModel.id).where(PlanModel.is_default))
        session.execute(
            delete(SubscriptionModel).where(SubscriptionModel.tenant_id == tenant_id)
        )
        session.add(
            SubscriptionModel(tenant_id=tenant_id, plan_id=plan_id, status="cancelled")
        )
        session.commit()
    subscription_access().forget()
    try:
        error = api.error("POST", "/api/admin/customers", 403, json={"name": "X"})
        assert error["code"] == "SUBSCRIPTION_READ_ONLY"
        assert api.post("/api/admin/data-exports")["status"] == "QUEUED"
    finally:
        with Session(bind=pg_engine) as session:
            session.execute(
                delete(SubscriptionModel).where(
                    SubscriptionModel.tenant_id == tenant_id
                )
            )
            session.commit()
        subscription_access().forget()


def test_an_export_expires_and_its_file_is_deleted(api, pg_engine):
    export_id = _export(api)
    job = api.get(f"/api/admin/data-exports/{export_id}")
    path = export_file(ensure_tenant(pg_engine), _file_name(pg_engine, export_id))
    assert path.is_file() and job["fileSize"] == path.stat().st_size

    expired = purge_files(worker_session_maker(), datetime.now() + timedelta(days=8))

    assert expired == 1
    assert not path.exists()
    assert api.get(f"/api/admin/data-exports/{export_id}")["status"] == "EXPIRED"
    assert (
        api.error("GET", f"/api/admin/data-exports/{export_id}/download", 409)["code"]
        == "EXPORT_NOT_READY"
    )


def _file_name(pg_engine, export_id: int) -> str:
    with pg_engine.connect() as conn:
        return conn.execute(
            text("SELECT file_name FROM export_jobs WHERE id = :i"), {"i": export_id}
        ).scalar_one()
