"""The termination of a company's contract on PostgreSQL (S8.7): the grace
period, the anonymization that keeps what tax law requires and removes the rest,
the purge after the retention, and another company untouched all along.

Two companies with the isolation suite's graph (customers, sales, a shift and
its closing, an integration client, webhooks, imports, invoices, credit notes)
are built through the API; the first one is offboarded."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from src.data_protection.app.commands.offboarding import (
    AnonymizeTenantCommand,
    AnonymizeTenantCommandHandler,
    CancelOffboardingCommand,
    CancelOffboardingCommandHandler,
    PurgeTenantCommand,
    PurgeTenantCommandHandler,
    StartOffboardingCommand,
    StartOffboardingCommandHandler,
)
from src.data_protection.app.offboarding import TenantDataCleaner
from src.data_protection.domain.exceptions import (
    GraceNotEndedError,
    OffboardingStepError,
    PendingMessagesError,
    RetentionNotEndedError,
)
from src.data_protection.infra.cleaner import PURGE_ON_ANONYMIZE
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.database import worker_session_maker
from src.shared.infra.events.scope import create_sync_scope
from src.subscriptions.infra.guard import subscription_access
from tests.integration.postgres.api import Api
from tests.integration.postgres.isolation.dataset import build_tenant
from tests.integration.postgres.isolation.harness import tenant_rows
from tests.integration.postgres.support import issue_headers
from tests.integration.postgres.tenants import OTHER_TENANT_RUC, ensure_tenant

GRACE = 30
YEARS = 7


@pytest.fixture(autouse=True)
def _fresh_status():
    subscription_access().forget()
    yield
    subscription_access().forget()


@pytest.fixture
def companies(client, pg_engine):
    a_id = ensure_tenant(pg_engine)
    a = Api(client, issue_headers(pg_engine, tenant_id=a_id, username="admin-a"))
    ids = build_tenant(a, "AAA", 1, a_id)
    # A closed shift leaves its Z closing: append-only for the app and the worker
    in_branch = Api(client, {**a.headers, "X-Branch-Id": str(ids["branch"])})
    in_branch.post(
        f"/api/pos/shifts/{ids['shift']}/close",
        {
            "counts": [
                {
                    "paymentMethod": "CASH",
                    "counted": "0.00",
                    "justification": "Arqueo de prueba de la baja",
                }
            ]
        },
    )
    b_id = ensure_tenant(pg_engine, OTHER_TENANT_RUC)
    b = Api(client, issue_headers(pg_engine, tenant_id=b_id, username="admin-b"))
    build_tenant(b, "ZZB", 2, b_id)
    return a_id, a, b_id, b


def _run(tenant_id, handler, command):
    """What the console and the CLI do: the worker's session, in the tenant"""
    context = TenantContext(tenant_id, TenantSource.TASK, user_name="Ops")
    with worker_session_maker()() as session:
        with create_sync_scope(session, tenant=context) as scope:
            result = scope.get(handler).handle(command)
        session.commit()
    return result


def _plan(tenant_id):
    context = TenantContext(tenant_id, TenantSource.TASK, user_name="Ops")
    with (
        worker_session_maker()() as session,
        create_sync_scope(session, tenant=context) as scope,
    ):
        return scope.get(TenantDataCleaner).plan(tenant_id)


def _start(tenant_id, now=None):
    return _run(
        tenant_id,
        StartOffboardingCommandHandler,
        StartOffboardingCommand(grace_days=GRACE, retention_years=YEARS, now=now),
    )


def _count(engine, table, tenant_id) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text(f'SELECT count(*) FROM "{table}" WHERE tenant_id = :t'),
            {"t": tenant_id},
        ).scalar_one()


def _outbox_published(engine, tenant_id) -> None:
    """Nothing waits for Kafka in these tests: what the sales left is delivered"""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE outbox_messages SET status = 'published', "
                "published_at = now() WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        )


def test_starting_cancels_the_subscription_and_sets_the_dates(companies, pg_engine):
    a_id, a, _, _ = companies
    now = datetime(2026, 11, 25, 10, 0)

    result = _start(a_id, now)

    assert result["offboarding_started_at"] == now
    assert result["grace_ends_at"] == now + timedelta(days=GRACE)
    # Tax retention counts from the last sale, 7 years on
    last_sale = _last_sale(pg_engine, a_id)
    assert result["retention_ends_at"].year == last_sale.year + YEARS
    # Read-only now, but it still takes its data out and signs in
    subscription_access().forget()
    error = a.error("POST", "/api/admin/categories", 403, json={"name": "X"})
    assert error["code"] == "SUBSCRIPTION_READ_ONLY"
    assert a.post("/api/admin/data-exports")["status"] == "QUEUED"
    assert a.get("/api/auth/me")["subscription"]["status"] == "cancelled"
    # Audited in the company's log, signed by the operator
    with pg_engine.connect() as conn:
        [entry] = conn.execute(
            text(
                "SELECT actor_name, source FROM audit_log "
                "WHERE tenant_id = :t AND action = 'tenant.offboarding_started'"
            ),
            {"t": a_id},
        ).all()
    assert tuple(entry) == ("Ops", "task")


def _last_sale(engine, tenant_id) -> datetime:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT max(created_at) FROM sales WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).scalar_one()


def test_the_offboarding_can_be_taken_back_before_anonymizing(companies, pg_engine):
    a_id, a, _, _ = companies
    _start(a_id)

    back = _run(a_id, CancelOffboardingCommandHandler, CancelOffboardingCommand())

    assert back["offboarding_started_at"] is None and back["grace_ends_at"] is None
    subscription_access().forget()
    assert a.post("/api/admin/categories", {"name": "De nuevo"})["id"]


def test_anonymizing_waits_for_the_grace_period_and_for_the_messages(
    companies, pg_engine
):
    a_id, _, _, _ = companies
    with pytest.raises(OffboardingStepError):
        _run(a_id, AnonymizeTenantCommandHandler, AnonymizeTenantCommand())
    _start(a_id)

    with pytest.raises(GraceNotEndedError):
        _run(a_id, AnonymizeTenantCommandHandler, AnonymizeTenantCommand())
    # The grace period over, but the invoicing messages of its sales are pending
    later = datetime.now() + timedelta(days=GRACE + 1)
    with pytest.raises(PendingMessagesError):
        _run(a_id, AnonymizeTenantCommandHandler, AnonymizeTenantCommand(now=later))


def test_anonymizing_keeps_what_tax_law_requires_and_removes_the_rest(
    companies, pg_engine
):
    a_id, _, b_id, b = companies
    b_before = tenant_rows(pg_engine, b_id)
    _outbox_published(pg_engine, a_id)
    _start(a_id)
    plan = _plan(a_id)
    kept = {
        table: _count(pg_engine, table, a_id)
        for table in (
            "sales",
            "sale_items",
            "payments",
            "customers",
            "suppliers",
            "products",
            "movements",
            "stocks",
            "purchase_orders",
            "credit_notes",
            "pos_shift_closings",
            "audit_log",
        )
    }
    customers_before = _customers(pg_engine, a_id)
    assert kept["sales"] and kept["customers"] and kept["pos_shift_closings"]
    assert plan["purge"].get("memberships") and plan["anonymize"]["customers"]

    result = _run(
        a_id,
        AnonymizeTenantCommandHandler,
        AnonymizeTenantCommand(skip_grace=True),
    )

    assert result["status"] == "offboarded" and result["anonymized_at"]
    # What is deleted: access, integrations, webhooks, imports, contacts
    for table in PURGE_ON_ANONYMIZE:
        assert _count(pg_engine, table, a_id) == 0, table
    # What is kept: the accounting, row for row (the audit log gains one entry)
    for table, rows in kept.items():
        expected = rows + 1 if table == "audit_log" else rows
        assert _count(pg_engine, table, a_id) == expected, table
    after = _customers(pg_engine, a_id)
    # Tax identification and type stay: they identify the buyer of an invoice
    assert [(c.tax_id, c.tax_type) for c in after] == [
        (c.tax_id, c.tax_type) for c in customers_before
    ]
    for customer in after:
        assert customer.name.startswith("Cliente anonimizado ")
        assert (customer.email, customer.phone, customer.address) == (None,) * 3
    _no_personal_data_left(pg_engine, a_id)
    # Nobody signs in any more
    # (An access token already issued lasts its 15 minutes, as after a
    # suspension; no session can refresh it and no membership logs in again)
    assert _count(pg_engine, "auth_sessions", a_id) == 0
    assert _count(pg_engine, "memberships", a_id) == 0
    assert _tenant(pg_engine, a_id)["status"] == "offboarded"
    # The other company is exactly as it was
    assert tenant_rows(pg_engine, b_id) == b_before
    assert b.get("/api/admin/customers")
    # A second time is refused, and so is bringing it back
    with pytest.raises(OffboardingStepError):
        _run(
            a_id, AnonymizeTenantCommandHandler, AnonymizeTenantCommand(skip_grace=True)
        )
    with pytest.raises(Exception, match="offboarded"):
        _run(a_id, CancelOffboardingCommandHandler, CancelOffboardingCommand())


def _customers(engine, tenant_id):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT id, name, tax_id, tax_type, email, phone, address "
                "FROM customers WHERE tenant_id = :t ORDER BY id"
            ),
            {"t": tenant_id},
        ).all()


def _tenant(engine, tenant_id) -> dict:
    with engine.connect() as conn:
        return dict(
            conn.execute(text("SELECT * FROM tenants WHERE id = :t"), {"t": tenant_id})
            .mappings()
            .one()
        )


def _no_personal_data_left(engine, tenant_id) -> None:
    """The names of people and the free text of what is kept are gone"""
    with engine.connect() as conn:
        authors = conn.execute(
            text(
                "SELECT count(*) FROM sales WHERE tenant_id = :t "
                "AND (notes IS NOT NULL OR created_by NOT IN ('Usuario anonimizado'))"
            ),
            {"t": tenant_id},
        ).scalar_one()
        assert authors == 0
        cashiers = (
            conn.execute(
                text(
                    "SELECT DISTINCT cashier_name FROM pos_shifts WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
            .scalars()
            .all()
        )
        assert set(cashiers) == {"Cajero anonimizado"}
        closings = (
            conn.execute(
                text(
                    "SELECT DISTINCT cashier_name FROM pos_shift_closings "
                    "WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
            .scalars()
            .all()
        )
        assert set(closings) == {"Cajero anonimizado"}
        audit = conn.execute(
            text(
                "SELECT actor_name, count(*) FROM audit_log WHERE tenant_id = :t "
                "AND action NOT LIKE 'tenant.%' GROUP BY actor_name"
            ),
            {"t": tenant_id},
        ).all()
        assert {row[0] for row in audit} <= {"Usuario anonimizado", None}
        users = conn.execute(
            text(
                "SELECT username, email, full_name, is_active FROM users "
                "WHERE username LIKE 'anonimizado-%'"
            )
        ).all()
        assert users and all(not u.is_active and u.full_name is None for u in users)


def test_purging_waits_for_the_retention_and_deletes_every_row(companies, pg_engine):
    a_id, _, b_id, b = companies
    _outbox_published(pg_engine, a_id)
    b_before = tenant_rows(pg_engine, b_id)
    _start(a_id)
    _run(a_id, AnonymizeTenantCommandHandler, AnonymizeTenantCommand(skip_grace=True))
    retention_ends = _tenant(pg_engine, a_id)["retention_ends_at"]

    with pytest.raises(OffboardingStepError, match="RUC"):
        _run(a_id, PurgeTenantCommandHandler, PurgeTenantCommand(confirm_ruc="x"))
    ruc = _tenant(pg_engine, a_id)["ruc"]
    with pytest.raises(RetentionNotEndedError):
        _run(a_id, PurgeTenantCommandHandler, PurgeTenantCommand(confirm_ruc=ruc))

    result = _run(
        a_id,
        PurgeTenantCommandHandler,
        PurgeTenantCommand(confirm_ruc=ruc, now=retention_ends + timedelta(days=1)),
    )

    assert result["purged"] and result["deleted"]["tenants"] == 1
    with pg_engine.connect() as conn:
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE column_name = 'tenant_id' AND table_schema = 'public'"
            )
        ).scalars()
        for table in tables:
            left = conn.execute(
                text(f'SELECT count(*) FROM "{table}" WHERE tenant_id = :t'),
                {"t": a_id},
            ).scalar_one()
            assert left == 0, table
        assert (
            conn.execute(
                text("SELECT count(*) FROM tenants WHERE id = :t"), {"t": a_id}
            ).scalar_one()
            == 0
        )
    assert tenant_rows(pg_engine, b_id) == b_before
    assert b.get("/api/admin/customers")


def test_the_worker_anonymizes_only_what_is_due_and_only_when_asked(
    companies, pg_engine, monkeypatch
):
    from config import config
    from src.data_protection.infra.offboarding_task import anonymize_due

    a_id, _, b_id, _ = companies
    _outbox_published(pg_engine, a_id)
    # Started 40 days ago: its grace period (30) is over; B never started
    _start(a_id, datetime.now() - timedelta(days=40))

    monkeypatch.setattr(config, "OFFBOARDING_AUTO_ANONYMIZE", False)
    assert anonymize_due() == 0
    assert _tenant(pg_engine, a_id)["anonymized_at"] is None

    monkeypatch.setattr(config, "OFFBOARDING_AUTO_ANONYMIZE", True)
    assert anonymize_due() == 1
    assert _tenant(pg_engine, a_id)["status"] == "offboarded"
    assert _tenant(pg_engine, b_id)["status"] == "active"
    assert anonymize_due() == 0


def test_the_cli_shows_a_plan_without_writing_and_refuses_a_purge_in_advance(
    companies, pg_engine
):
    from src.data_protection.cli import _parser, run

    a_id, _, _, _ = companies
    ruc = _tenant(pg_engine, a_id)["ruc"]
    before = tenant_rows(pg_engine, a_id)

    plan = run(_parser().parse_args(["plan", "--ruc", ruc, "--by", "Ops"]))
    dry = run(_parser().parse_args(["anonymize", "--ruc", ruc, "--by", "Ops"]))

    assert plan == dry and plan["retain"]["sales"] and plan["purge"]["memberships"]
    assert tenant_rows(pg_engine, a_id) == before
    with pytest.raises(OffboardingStepError):
        run(
            _parser().parse_args(
                [
                    "purge",
                    "--ruc",
                    ruc,
                    "--by",
                    "Ops",
                    "--confirm-ruc",
                    ruc,
                    "--execute",
                ]
            )
        )


def test_the_cli_writes_the_export_without_the_application(companies, pg_engine):
    import zipfile
    from pathlib import Path

    from src.data_protection.cli import _parser, run

    a_id, _, _, _ = companies
    ruc = _tenant(pg_engine, a_id)["ruc"]

    result = run(_parser().parse_args(["export", "--ruc", ruc, "--by", "Ops"]))

    archive = zipfile.ZipFile(Path(result["file"]))
    assert (
        "customers.csv" in archive.namelist() and "manifest.json" in archive.namelist()
    )
    assert str(a_id) in result["file"]
