"""Audit log (S3.5): what an entry keeps and how the log is read, on SQLite.
Each action of the catalog, the transaction and the privileges are checked on
PostgreSQL (`tests/integration/postgres/test_audit_log.py`)."""

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.audit.app.queries.audit_log import ListAuditLogQuery, ListAuditLogQueryHandler
from src.audit.infra.models import AuditLogModel
from src.audit.infra.trail import SqlAlchemyAuditTrail
from src.auth.domain.entities import Role
from src.shared.app.audit import AuditAction, changed, snapshot
from src.shared.domain.tenant import (
    TenantContext,
    TenantContextRequiredError,
    TenantSource,
    use_tenant,
)
from src.tenancy.infra.models import TenantModel
from tests.conftest import TEST_TENANT_ID
from tests.sqlite import sqlite_session

OTHER_TENANT = UUID("00000000-0000-4000-8000-00000000000b")
REQUEST_ID = "6f1c3d1e-6b1a-4a43-9d0e-6a7f2f6b9e51"

CASHIER = TenantContext(
    TEST_TENANT_ID,
    TenantSource.REQUEST,
    user_id=7,
    branch_id=3,
    user_name="Caja Uno",
)


@pytest.fixture
def session() -> Iterator[Session]:
    session = sqlite_session([AuditLogModel])
    session.add(TenantModel(id=OTHER_TENANT, ruc="1799999991001", legal_name="Otra"))
    session.commit()
    yield session
    session.close()


def _entries(session: Session) -> list[AuditLogModel]:
    return list(session.scalars(select(AuditLogModel).order_by(AuditLogModel.id)))


def test_the_actor_source_branch_and_request_come_from_the_context(session):
    with (
        use_tenant(CASHIER),
        structlog.contextvars.bound_contextvars(**{"http.request.id": REQUEST_ID}),
    ):
        SqlAlchemyAuditTrail(session).record(
            AuditAction.SALE_CANCELLED,
            41,
            before={"status": "CONFIRMED"},
            after={"status": "CANCELLED", "reason": "Error de cobro"},
        )

    (entry,) = _entries(session)
    assert entry.tenant_id == TEST_TENANT_ID
    assert (entry.actor_user_id, entry.actor_name) == (7, "Caja Uno")
    assert (entry.action, entry.resource_type, entry.resource_id) == (
        "sale.cancelled",
        "sale",
        41,
    )
    assert entry.source == "request"
    assert entry.branch_id == 3
    assert entry.request_id == REQUEST_ID
    assert entry.before == {"status": "CONFIRMED"}
    assert entry.after == {"status": "CANCELLED", "reason": "Error de cobro"}


def test_the_resources_branch_wins_over_the_requests(session):
    with use_tenant(CASHIER):
        SqlAlchemyAuditTrail(session).record(
            AuditAction.REFUND_CANCELLED, 5, branch_id=9
        )

    assert _entries(session)[0].branch_id == 9


def test_a_task_has_no_actor_nor_request(session, in_tenant):
    SqlAlchemyAuditTrail(session).record(AuditAction.PRODUCT_DELETED, 1)

    (entry,) = _entries(session)
    assert (entry.actor_user_id, entry.actor_name, entry.request_id) == (
        None,
        None,
        None,
    )
    assert entry.source == "task"


def test_values_are_stored_as_json(session, in_tenant):
    SqlAlchemyAuditTrail(session).record(
        AuditAction.PRODUCT_PRICE_CHANGED,
        1,
        after={
            "sale_price": Decimal("12.500000"),
            "role": Role.CASHIER,
            "day": date(2026, 10, 28),
            "at": datetime(2026, 10, 28, 9, 30),
            "branch_ids": {3, 1},
            "items": [{"quantity": Decimal("2")}],
        },
    )

    assert _entries(session)[0].after == {
        "sale_price": "12.500000",
        "role": 5,
        "day": "2026-10-28",
        "at": "2026-10-28T09:30:00",
        "branch_ids": [1, 3],
        "items": [{"quantity": "2"}],
    }


def test_a_secret_never_reaches_the_log(session, in_tenant):
    SqlAlchemyAuditTrail(session).record(
        AuditAction.USER_PASSWORD_RESET,
        1,
        before={"password": "old", "username": "ana"},
        after={"nested": {"new_password": "x", "token": "y", "ok": True}},
    )

    entry = _entries(session)[0]
    assert entry.before == {"username": "ana"}
    assert entry.after == {"nested": {"ok": True}}


def test_without_a_tenant_it_fails(session):
    with pytest.raises(TenantContextRequiredError):
        SqlAlchemyAuditTrail(session).record(AuditAction.PRODUCT_CREATED, 1)


def test_the_resource_is_the_prefix_of_the_action():
    assert AuditAction.POS_TERMINAL_UPDATED.resource == "pos_terminal"
    assert AuditAction.CASH_MOVEMENT_REGISTERED.resource == "cash_movement"
    assert all("." in action.value for action in AuditAction)


def test_changed_keeps_only_what_changed():
    class Point:
        code, name, is_active = "001", "Caja", True

    before = snapshot(Point(), "code", "name", "is_active")

    assert changed(before, {**before, "name": "Caja 1"}) == (
        {"name": "Caja"},
        {"name": "Caja 1"},
    )
    assert changed(before, before) == ({}, {})


# Reading the log


def _log(session: Session, context: TenantContext, **query) -> dict:
    with use_tenant(context):
        return ListAuditLogQueryHandler(session).handle(ListAuditLogQuery(**query))


def _seed(session: Session) -> None:
    trail = SqlAlchemyAuditTrail(session)
    with use_tenant(CASHIER):
        trail.record(AuditAction.SHIFT_OPENED, 1)
        trail.record(AuditAction.SALE_CANCELLED, 41, branch_id=4)
    admin = TenantContext(
        TEST_TENANT_ID, TenantSource.REQUEST, user_id=1, user_name="Admin"
    )
    with use_tenant(admin):
        trail.record(AuditAction.PRODUCT_PRICE_CHANGED, 10)
    with use_tenant(TenantContext(OTHER_TENANT, TenantSource.REQUEST, user_id=1)):
        trail.record(AuditAction.PRODUCT_PRICE_CHANGED, 10)


def test_the_log_is_the_tenants_newest_first(session):
    _seed(session)

    result = _log(session, CASHIER)

    assert result["total"] == 3
    assert [item["action"] for item in result["items"]] == [
        "product.price_changed",
        "sale.cancelled",
        "shift.opened",
    ]


@pytest.mark.parametrize(
    ("query", "actions"),
    [
        ({"actor_id": 7}, ["sale.cancelled", "shift.opened"]),
        ({"action": "sale.cancelled"}, ["sale.cancelled"]),
        ({"resource_type": "product"}, ["product.price_changed"]),
        ({"resource_type": "sale", "resource_id": 41}, ["sale.cancelled"]),
        ({"branch_id": 4}, ["sale.cancelled"]),
        ({"branch_id": 3}, ["shift.opened"]),
    ],
)
def test_the_log_is_filtered(session, query, actions):
    _seed(session)

    result = _log(session, CASHIER, **query)

    assert [item["action"] for item in result["items"]] == actions
    assert result["total"] == len(actions)


def test_the_log_is_filtered_by_whole_days(session):
    _seed(session)
    today = date.today()

    assert _log(session, CASHIER, from_date=today, to_date=today)["total"] == 3
    assert _log(session, CASHIER, to_date=today - timedelta(days=1))["total"] == 0
    assert _log(session, CASHIER, from_date=today + timedelta(days=1))["total"] == 0


def test_the_log_is_paginated(session):
    _seed(session)

    result = _log(session, CASHIER, limit=1, offset=1)

    assert (result["total"], result["limit"], result["offset"]) == (3, 1, 1)
    assert [item["action"] for item in result["items"]] == ["sale.cancelled"]
