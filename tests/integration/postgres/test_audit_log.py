"""Audit log (S3.5): every action of the catalog, driven through the API as a
user with a full name, leaves exactly one entry with the token's actor, written
in the operation's transaction; the app can't change nor delete entries."""

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from config import config
from src.audit.infra.models import AuditLogModel
from src.auth.domain.entities import Role
from src.invoicing.infra.reconciliation import reconcile
from src.shared.app.audit import AuditAction
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.shared.infra.database import create_session_maker
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    make_branch,
    make_location,
    make_movement,
    make_product,
    make_terminal,
    make_warehouse,
)

INSUFFICIENT_PRIVILEGE = "42501"
REQUEST_ID = "X-Request-Id"


@dataclass
class Actor:
    api: Api
    name: str
    user_id: int


@dataclass
class World:
    admin: Actor
    cashier: Actor
    manager: Actor
    warehouse: dict
    shelf: dict
    backroom: dict
    terminal: dict
    # The audited call: who made it and its X-Request-Id
    actor: Actor | None = None
    request_id: str | None = None
    created: dict[str, Any] = field(default_factory=dict)

    def send(self, actor: Actor, method: str, path: str, json=None) -> Any:
        """The call under test, with its own X-Request-Id"""
        self.actor, self.request_id = actor, str(uuid4())
        return actor.api.request(
            method, path, json=json, headers={REQUEST_ID: self.request_id}
        )


def _user_id(engine: Engine, username: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM users WHERE username = :u"), {"u": username}
        ).scalar_one()


@pytest.fixture
def world(client, auth_headers, pg_engine) -> World:
    def actor(role: Role, name: str, username: str, terminal=None) -> Actor:
        headers = auth_headers(role, full_name=name, username=username)
        if terminal is not None:
            headers = at_terminal(headers, terminal)
        return Actor(Api(client, headers), name, _user_id(pg_engine, username))

    admin = actor(Role.ADMIN, "Admin Uno", "admin-audit")
    warehouse = make_warehouse(admin.api)
    shelf = make_location(admin.api, warehouse["id"], "A1")
    backroom = make_location(admin.api, warehouse["id"], "B1")
    terminal = make_terminal(admin.api, shelf["id"])
    return World(
        admin=admin,
        cashier=actor(Role.CASHIER, "Caja Uno", "cashier-audit", terminal),
        manager=actor(Role.MANAGER, "Gerente Uno", "manager-audit", terminal),
        warehouse=warehouse,
        shelf=shelf,
        backroom=backroom,
        terminal=terminal,
    )


def _product(w: World, stock: int = 10, location: str = "shelf") -> dict:
    product = make_product(w.admin.api, sku=f"SKU-{uuid4().hex[:6]}", salePrice="10.00")
    if stock:
        location_id = w.shelf["id"] if location == "shelf" else w.backroom["id"]
        make_movement(w.admin.api, product["id"], stock, location_id)
    return product


def _product_body(product: dict, **changes) -> dict:
    return {
        "name": product["name"],
        "sku": product["sku"],
        "purchasePrice": "6.00",
        "salePrice": "10.00",
        "taxCode": "VAT_15",
        **changes,
    }


def _shift(w: World) -> dict:
    return w.cashier.api.post("/api/pos/shifts/open", {"openingBalance": "50.00"})


def _quick_sale(w: World) -> dict:
    product = _product(w)
    return w.cashier.api.post(
        "/api/pos/sales/quick",
        {
            "items": [{"productId": product["id"], "quantity": 1}],
            "payments": [{"amount": "11.50", "paymentMethod": "CASH"}],
        },
    )


def _draft_sale_with_item(w: World) -> tuple[dict, dict]:
    product = _product(w)
    sale = w.cashier.api.post("/api/pos/sales", {"isFinalConsumer": True})
    item = w.cashier.api.post(
        f"/api/pos/sales/{sale['id']}/items",
        {"productId": product["id"], "quantity": 1, "unitPrice": "10.00"},
    )
    return sale, item


def _refund(w: World) -> dict:
    _shift(w)
    sale = _quick_sale(w)
    [item] = w.cashier.api.get(f"/api/pos/sales/{sale['id']}/items")
    return w.cashier.api.post(
        "/api/pos/refunds",
        {
            "originalSaleId": sale["id"],
            "items": [{"saleItemId": item["id"], "quantity": 1}],
        },
    )


def _adjustment(w: World) -> dict:
    return w.admin.api.post(
        "/api/admin/adjustments",
        {"warehouseId": w.warehouse["id"], "reason": "physical_count"},
    )


def _transfer(w: World, confirmed: bool = False) -> dict:
    product = _product(w, location="backroom")
    transfer = w.admin.api.post(
        "/api/admin/transfers",
        {
            "sourceLocationId": w.backroom["id"],
            "destinationLocationId": w.shelf["id"],
        },
    )
    w.admin.api.post(
        f"/api/admin/transfers/{transfer['id']}/items",
        {"productId": product["id"], "quantity": 3},
    )
    if confirmed:
        w.admin.api.post(f"/api/admin/transfers/{transfer['id']}/confirm")
    return transfer


def _user(w: World, username: str = "nuevo") -> dict:
    return w.admin.api.post(
        "/api/admin/users",
        {
            "username": username,
            "email": f"{username}@test.local",
            "password": "Temporal-123",
            "role": int(Role.CASHIER),
            "fullName": "Nuevo Usuario",
        },
    )


def _emission_point(w: World) -> dict:
    return w.admin.api.post(
        "/api/admin/emission-points",
        {"branchId": w.terminal["branchId"], "code": "002", "name": "Caja 2"},
    )


def _new_terminal(w: World) -> dict:
    return w.admin.api.post(
        "/api/admin/pos-terminals",
        {
            "branchId": w.terminal["branchId"],
            "emissionPointId": w.terminal["emissionPointId"],
            "defaultLocationId": w.shelf["id"],
            "code": "CAJA-02",
            "name": "Caja 2",
        },
    )


# One scenario per action: it prepares what it needs and makes the audited call
# with `w.send`, returning the resource id the entry must carry


def _product_created(w):
    return w.send(
        w.admin,
        "POST",
        "/api/admin/products",
        _product_body({"name": "Taladro", "sku": "TAL-1"}),
    )["id"]


def _product_updated(w):
    product = _product(w, stock=0)
    body = _product_body(product, name="Taladro 600W")
    return w.send(w.admin, "PUT", f"/api/admin/products/{product['id']}", body)["id"]


def _product_price_changed(w):
    product = _product(w, stock=0)
    body = _product_body(product, salePrice="12.50")
    return w.send(w.admin, "PUT", f"/api/admin/products/{product['id']}", body)["id"]


def _product_deleted(w):
    product = _product(w, stock=0)
    w.send(w.admin, "DELETE", f"/api/admin/products/{product['id']}")
    return product["id"]


def _movement_created(w):
    product = _product(w, stock=0)
    return w.send(
        w.admin,
        "POST",
        "/api/admin/movements",
        {
            "productId": product["id"],
            "quantity": 5,
            "type": "IN",
            "locationId": w.shelf["id"],
        },
    )["id"]


def _adjustment_confirmed(w):
    product = _product(w)
    adjustment = _adjustment(w)
    w.admin.api.post(
        f"/api/admin/adjustments/{adjustment['id']}/items",
        {"productId": product["id"], "locationId": w.shelf["id"], "actualQuantity": 7},
    )
    w.send(w.admin, "POST", f"/api/admin/adjustments/{adjustment['id']}/confirm")
    return adjustment["id"]


def _adjustment_cancelled(w):
    adjustment = _adjustment(w)
    w.send(w.admin, "POST", f"/api/admin/adjustments/{adjustment['id']}/cancel")
    return adjustment["id"]


def _transfer_confirmed(w):
    transfer = _transfer(w)
    w.send(w.admin, "POST", f"/api/admin/transfers/{transfer['id']}/confirm")
    return transfer["id"]


def _transfer_received(w):
    transfer = _transfer(w, confirmed=True)
    w.send(w.admin, "POST", f"/api/admin/transfers/{transfer['id']}/receive")
    return transfer["id"]


def _transfer_cancelled(w):
    transfer = _transfer(w, confirmed=True)
    w.send(w.admin, "POST", f"/api/admin/transfers/{transfer['id']}/cancel")
    return transfer["id"]


def _sale_cancelled(w):
    _shift(w)
    sale = _quick_sale(w)
    path = f"/api/pos/sales/{sale['id']}/cancel"
    w.send(w.cashier, "POST", path, {"reason": "Error de cobro"})
    return sale["id"]


def _sale_price_overridden(w):
    _shift(w)
    sale, item = _draft_sale_with_item(w)
    path = f"/api/pos/sales/{sale['id']}/items/{item['id']}/price"
    w.send(w.cashier, "PUT", path, {"newPrice": "9.00", "reason": "Cliente frecuente"})
    return sale["id"]


def _sale_discount_applied(w):
    _shift(w)
    sale, _ = _draft_sale_with_item(w)
    path = f"/api/pos/sales/{sale['id']}/discount"
    w.send(w.cashier, "POST", path, {"discountType": "PERCENTAGE", "discountValue": 5})
    return sale["id"]


def _sale_invoice_requested(w):
    _shift(w)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(config, "KAFKA_ENABLED", True)
        sale = _quick_sale(w)
        w.send(w.admin, "POST", f"/api/admin/sales/{sale['id']}/request-invoice")
    return sale["id"]


def _invoice_discrepancy_reviewed(w):
    _shift(w)
    _quick_sale(w)
    with pytest.MonkeyPatch.context() as patch:
        # Every confirmed sale without an invoice result is overdue
        patch.setattr(config, "INVOICE_RECONCILIATION_PENDING_MINUTES", -1)
        reconcile()
    [discrepancy] = w.admin.api.get("/api/admin/invoice-discrepancies")
    path = f"/api/admin/invoice-discrepancies/{discrepancy['id']}/review"
    w.send(w.manager, "POST", path, {"note": "Revisado con facturación"})
    return discrepancy["id"]


def _refund_processed(w):
    refund = _refund(w)
    w.send(
        w.manager,
        "POST",
        f"/api/pos/refunds/{refund['id']}/process",
        {"payments": [{"amount": "11.50", "paymentMethod": "CASH"}]},
    )
    return refund["id"]


def _refund_cancelled(w):
    refund = _refund(w)
    w.send(w.cashier, "POST", f"/api/pos/refunds/{refund['id']}/cancel")
    return refund["id"]


def _cash_movement_registered(w):
    shift = _shift(w)
    return w.send(
        w.cashier,
        "POST",
        f"/api/pos/shifts/{shift['id']}/cash-movements",
        {"type": "OUT", "amount": "5.00", "reason": "Cambio"},
    )["id"]


def _shift_opened(w):
    path = "/api/pos/shifts/open"
    return w.send(w.cashier, "POST", path, {"openingBalance": "50.00"})["id"]


def _shift_closed(w):
    shift = _shift(w)
    path = f"/api/pos/shifts/{shift['id']}/close"
    w.send(w.cashier, "POST", path, {"closingBalance": "50.00"})
    return shift["id"]


def _user_created(w):
    return w.send(
        w.admin,
        "POST",
        "/api/admin/users",
        {
            "username": "creado",
            "email": "creado@test.local",
            "password": "Temporal-123",
            "role": int(Role.CASHIER),
        },
    )["id"]


def _user_role_changed(w):
    user = _user(w)
    path = f"/api/admin/users/{user['id']}/role"
    w.send(w.admin, "PUT", path, {"role": int(Role.MANAGER)})
    return user["id"]


def _user_branches_changed(w):
    user = _user(w)
    path = f"/api/admin/users/{user['id']}/branches"
    w.send(w.admin, "PUT", path, {"branchIds": [w.terminal["branchId"]]})
    return user["id"]


def _user_renamed(w):
    user = _user(w)
    path = f"/api/admin/users/{user['id']}/profile"
    w.send(w.admin, "PUT", path, {"fullName": "Nombre Nuevo"})
    return user["id"]


def _user_activated(w):
    user = _user(w)
    w.admin.api.post(f"/api/admin/users/{user['id']}/deactivate")
    w.send(w.admin, "POST", f"/api/admin/users/{user['id']}/activate")
    return user["id"]


def _user_deactivated(w):
    user = _user(w)
    w.send(w.admin, "POST", f"/api/admin/users/{user['id']}/deactivate")
    return user["id"]


def _user_password_reset(w):
    user = _user(w)
    path = f"/api/admin/users/{user['id']}/reset-password"
    w.send(w.admin, "POST", path, {"newPassword": "Otra-Clave-456"})
    return user["id"]


def _branch_created(w):
    body = {"establishmentCode": "002", "name": "Norte"}
    return w.send(w.admin, "POST", "/api/admin/branches", body)["id"]


def _branch_updated(w):
    branch = make_branch(w.admin.api, "002", "Norte")
    body = {"establishmentCode": "002", "name": "Norte 2"}
    return w.send(w.admin, "PUT", f"/api/admin/branches/{branch['id']}", body)["id"]


def _branch_deleted(w):
    branch = make_branch(w.admin.api, "002", "Norte")
    w.send(w.admin, "DELETE", f"/api/admin/branches/{branch['id']}")
    return branch["id"]


def _emission_point_created(w):
    body = {"branchId": w.terminal["branchId"], "code": "002"}
    return w.send(w.admin, "POST", "/api/admin/emission-points", body)["id"]


def _emission_point_updated(w):
    point = _emission_point(w)
    path = f"/api/admin/emission-points/{point['id']}"
    return w.send(w.admin, "PUT", path, {"code": "002", "name": "Caja 2B"})["id"]


def _emission_point_deleted(w):
    point = _emission_point(w)
    w.send(w.admin, "DELETE", f"/api/admin/emission-points/{point['id']}")
    return point["id"]


def _pos_terminal_created(w):
    return w.send(
        w.admin,
        "POST",
        "/api/admin/pos-terminals",
        {
            "branchId": w.terminal["branchId"],
            "emissionPointId": w.terminal["emissionPointId"],
            "defaultLocationId": w.shelf["id"],
            "code": "CAJA-02",
            "name": "Caja 2",
        },
    )["id"]


def _pos_terminal_updated(w):
    terminal = _new_terminal(w)
    return w.send(
        w.admin,
        "PUT",
        f"/api/admin/pos-terminals/{terminal['id']}",
        {
            "emissionPointId": terminal["emissionPointId"],
            "defaultLocationId": w.backroom["id"],
            "code": "CAJA-02",
            "name": "Caja 2",
        },
    )["id"]


def _pos_terminal_deleted(w):
    terminal = _new_terminal(w)
    w.send(w.admin, "DELETE", f"/api/admin/pos-terminals/{terminal['id']}")
    return terminal["id"]


SCENARIOS: dict[AuditAction, Callable[[World], int]] = {
    AuditAction.PRODUCT_CREATED: _product_created,
    AuditAction.PRODUCT_UPDATED: _product_updated,
    AuditAction.PRODUCT_PRICE_CHANGED: _product_price_changed,
    AuditAction.PRODUCT_DELETED: _product_deleted,
    AuditAction.MOVEMENT_CREATED: _movement_created,
    AuditAction.ADJUSTMENT_CONFIRMED: _adjustment_confirmed,
    AuditAction.ADJUSTMENT_CANCELLED: _adjustment_cancelled,
    AuditAction.TRANSFER_CONFIRMED: _transfer_confirmed,
    AuditAction.TRANSFER_RECEIVED: _transfer_received,
    AuditAction.TRANSFER_CANCELLED: _transfer_cancelled,
    AuditAction.SALE_CANCELLED: _sale_cancelled,
    AuditAction.SALE_PRICE_OVERRIDDEN: _sale_price_overridden,
    AuditAction.SALE_DISCOUNT_APPLIED: _sale_discount_applied,
    AuditAction.SALE_INVOICE_REQUESTED: _sale_invoice_requested,
    AuditAction.INVOICE_DISCREPANCY_REVIEWED: _invoice_discrepancy_reviewed,
    AuditAction.REFUND_PROCESSED: _refund_processed,
    AuditAction.REFUND_CANCELLED: _refund_cancelled,
    AuditAction.CASH_MOVEMENT_REGISTERED: _cash_movement_registered,
    AuditAction.SHIFT_OPENED: _shift_opened,
    AuditAction.SHIFT_CLOSED: _shift_closed,
    AuditAction.USER_CREATED: _user_created,
    AuditAction.USER_ROLE_CHANGED: _user_role_changed,
    AuditAction.USER_BRANCHES_CHANGED: _user_branches_changed,
    AuditAction.USER_RENAMED: _user_renamed,
    AuditAction.USER_ACTIVATED: _user_activated,
    AuditAction.USER_DEACTIVATED: _user_deactivated,
    AuditAction.USER_PASSWORD_RESET: _user_password_reset,
    AuditAction.BRANCH_CREATED: _branch_created,
    AuditAction.BRANCH_UPDATED: _branch_updated,
    AuditAction.BRANCH_DELETED: _branch_deleted,
    AuditAction.EMISSION_POINT_CREATED: _emission_point_created,
    AuditAction.EMISSION_POINT_UPDATED: _emission_point_updated,
    AuditAction.EMISSION_POINT_DELETED: _emission_point_deleted,
    AuditAction.POS_TERMINAL_CREATED: _pos_terminal_created,
    AuditAction.POS_TERMINAL_UPDATED: _pos_terminal_updated,
    AuditAction.POS_TERMINAL_DELETED: _pos_terminal_deleted,
}


def _entries_of_request(db_session: Session, request_id: str) -> list[AuditLogModel]:
    return list(
        db_session.scalars(
            select(AuditLogModel).where(AuditLogModel.request_id == request_id)
        )
    )


def test_every_action_has_its_scenario():
    assert set(SCENARIOS) == set(AuditAction)


@pytest.mark.parametrize("action", list(SCENARIOS), ids=str)
def test_each_action_leaves_one_entry_signed_by_the_token(
    world, db_session, tenant, action
):
    resource_id = SCENARIOS[action](world)

    assert world.actor is not None and world.request_id is not None
    [entry] = _entries_of_request(db_session, world.request_id)
    assert entry.action == action.value
    assert (entry.resource_type, entry.resource_id) == (action.resource, resource_id)
    assert (entry.actor_user_id, entry.actor_name) == (
        world.actor.user_id,
        world.actor.name,
    )
    assert entry.source == "request"
    assert entry.tenant_id == tenant
    # And the admin reads it in the log
    listed = world.admin.api.get(
        "/api/admin/audit-log", params={"action": action.value}
    )
    [shown] = [item for item in listed if item["id"] == entry.id]
    assert shown["requestId"] == world.request_id


def test_an_entry_keeps_the_relevant_fields_and_the_sales_branch(world, db_session):
    _sale_cancelled(world)

    [entry] = _entries_of_request(db_session, world.request_id or "")
    assert entry.branch_id == world.terminal["branchId"]
    # Money as the decimal string of its column, numeric(18, 6)
    assert entry.before == {"status": "CONFIRMED", "total": "11.500000"}
    assert entry.after == {"status": "CANCELLED", "reason": "Error de cobro"}


def test_a_user_entry_has_no_password_nor_email(world, db_session):
    _user_created(world)
    _user_password_reset(world)

    for entry in db_session.scalars(select(AuditLogModel)):
        stored = f"{entry.before} {entry.after}"
        assert "Temporal-123" not in stored
        assert "Otra-Clave-456" not in stored
        assert "@test.local" not in stored


# The operation's transaction


def test_the_entry_is_written_in_the_operations_transaction(world, pg_engine):
    product_id = _product_price_changed(world)

    with pg_engine.connect() as conn:
        entry_xmin = conn.execute(
            text("SELECT xmin::text FROM audit_log WHERE request_id = :r"),
            {"r": world.request_id},
        ).scalar_one()
        product_xmin = conn.execute(
            text("SELECT xmin::text FROM products WHERE id = :id"), {"id": product_id}
        ).scalar_one()
    assert entry_xmin == product_xmin


def test_a_failed_operation_leaves_no_entry(world, db_session):
    """The price override is recorded before the stock is taken: when the
    stock isn't there, the whole sale and its entry roll back"""
    _shift(world)
    product = _product(world, stock=1)

    error = world.cashier.api.error(
        "POST",
        "/api/pos/sales/quick",
        400,
        json={
            "items": [
                {
                    "productId": product["id"],
                    "quantity": 5,
                    "unitPrice": "9.00",
                    "overrideReason": "Cliente frecuente",
                }
            ],
            "payments": [{"amount": "60.00", "paymentMethod": "CASH"}],
        },
    )

    assert error["code"] == "INSUFFICIENT_STOCK"
    actions = {entry.action for entry in db_session.scalars(select(AuditLogModel))}
    assert AuditAction.SALE_PRICE_OVERRIDDEN.value not in actions


def test_a_quick_sale_records_each_new_price_and_its_discount(world, db_session):
    _shift(world)
    first, second = _product(world), _product(world)

    sale = world.send(
        world.cashier,
        "POST",
        "/api/pos/sales/quick",
        {
            "items": [
                {
                    "productId": first["id"],
                    "quantity": 1,
                    "unitPrice": "9.00",
                    "overrideReason": "Cliente frecuente",
                },
                {"productId": second["id"], "quantity": 1},
            ],
            "discountType": "AMOUNT",
            "discountValue": 1,
            "payments": [{"amount": "30.00", "paymentMethod": "CASH"}],
        },
    )

    entries = _entries_of_request(db_session, world.request_id or "")
    assert sorted(entry.action for entry in entries) == [
        AuditAction.SALE_DISCOUNT_APPLIED.value,
        AuditAction.SALE_PRICE_OVERRIDDEN.value,
    ]
    assert {entry.resource_id for entry in entries} == {sale["id"]}


# Immutability


@pytest.fixture
def app_session(pg_engine, tenant):
    """A session of faclab_app inside the tenant, as a request has"""
    factory = create_session_maker(os.environ["DATABASE_URL"])
    with use_tenant(TenantContext(tenant, TenantSource.TASK)), factory() as session:
        yield session
    factory.kw["bind"].dispose()


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log"],
    ids=["update", "delete"],
)
def test_the_app_cant_change_nor_delete_entries(world, app_session, statement):
    _branch_created(world)

    with pytest.raises(ProgrammingError) as error:
        app_session.execute(text(statement))

    assert getattr(error.value.orig, "pgcode", None) == INSUFFICIENT_PRIVILEGE


def test_only_inserting_and_reading_are_granted(pg_engine):
    with pg_engine.connect() as conn:
        privileges = {
            (role, privilege): conn.execute(
                text("SELECT has_table_privilege(:role, 'audit_log', :privilege)"),
                {"role": role, "privilege": privilege},
            ).scalar_one()
            for role in ("faclab_app", "faclab_worker")
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
        }

    assert {key for key, granted in privileges.items() if granted} == {
        ("faclab_app", "SELECT"),
        ("faclab_app", "INSERT"),
        ("faclab_worker", "SELECT"),
        ("faclab_worker", "INSERT"),
    }


# The route


def test_the_log_is_filtered_and_paginated(world):
    branch_id = _branch_created(world)
    _shift_opened(world)
    cashier_shift = world.request_id
    _product_created(world)
    api = world.admin.api

    def listed(**params) -> list[str]:
        return [
            entry["action"] for entry in api.get("/api/admin/audit-log", params=params)
        ]

    assert listed(actorId=world.cashier.user_id) == ["shift.opened"]
    assert listed(resourceType="branch", resourceId=branch_id) == ["branch.created"]
    assert listed(branchId=world.terminal["branchId"])[0] == "shift.opened"
    response = api.client.get(
        "/api/admin/audit-log",
        params={"limit": 1, "resourceType": "product"},
        headers=api.headers,
    )
    body = response.json()
    assert body["meta"]["pagination"]["limit"] == 1
    assert [entry["action"] for entry in body["data"]] == ["product.created"]
    [shift_entry] = api.get("/api/admin/audit-log", params={"action": "shift.opened"})
    assert shift_entry["requestId"] == cashier_shift
    assert shift_entry["actorName"] == "Caja Uno"


def test_only_the_admin_reads_the_log(client, auth_headers):
    manager = Api(client, auth_headers(Role.MANAGER))

    error = manager.error("GET", "/api/admin/audit-log", 403)

    assert error["code"] == "PERMISSION_DENIED"
