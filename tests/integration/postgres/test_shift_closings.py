"""The formal Z closing of a shift against PostgreSQL (S5.9, F-10): the count by
payment method, the justification over the threshold, the correlative per
terminal, the Z report read from the closing and not recalculated, the
documents a closed shift refuses (also while it closes) and the closing the
application can't change."""

import os
import threading
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

from main import app
from src.auth.domain.entities import Role
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.shared.infra.database import create_session_maker
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    concurrently,
    make_location,
    make_movement,
    make_product,
    make_terminal,
    make_warehouse,
    with_key,
)

INSUFFICIENT_PRIVILEGE = "42501"
Z_REPORT = "/api/pos/reports/z-report"


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def shelf(admin_api) -> dict:
    return make_location(admin_api, make_warehouse(admin_api)["id"])


@pytest.fixture
def terminal(admin_api, shelf) -> dict:
    """Terminal CAJA-01 of branch 001"""
    return make_terminal(admin_api, shelf["id"])


@pytest.fixture
def cashier(auth_headers) -> dict[str, str]:
    return auth_headers(Role.CASHIER, full_name="Ana Cajera")


@pytest.fixture
def api(client, cashier, terminal) -> Api:
    return Api(client, at_terminal(cashier, terminal))


@pytest.fixture
def manager(client, auth_headers, terminal) -> Api:
    return Api(client, at_terminal(auth_headers(Role.MANAGER), terminal))


@pytest.fixture
def product(admin_api, shelf) -> dict:
    """A VAT 15% product priced at 10.00 (11.50 with VAT), 20 on the shelf"""
    product = make_product(admin_api, salePrice="10.00", taxCode="VAT_15")
    make_movement(admin_api, product["id"], 20, shelf["id"])
    return product


@pytest.fixture
def shift(api) -> dict:
    return api.post("/api/pos/shifts/open", {"openingBalance": "100.00"})


def _sell(api: Api, product_id: int, method: str = "CASH", quantity: int = 1) -> dict:
    return api.post(
        "/api/pos/sales/quick",
        {
            "items": [{"productId": product_id, "quantity": quantity}],
            "payments": [
                {"amount": f"{Decimal('11.50') * quantity}", "paymentMethod": method}
            ],
        },
    )


def _count(method: str, counted: str, justification: str | None = None) -> dict:
    count = {"paymentMethod": method, "counted": counted}
    if justification is not None:
        count["justification"] = justification
    return count


def _close(api: Api, shift_id: int, *counts: dict, **extra) -> dict:
    return api.post(
        f"/api/pos/shifts/{shift_id}/close", {"counts": list(counts), **extra}
    )


def _z(api: Api, shift_id: int) -> dict:
    return api.get(Z_REPORT, params={"shiftId": shift_id})


# The count


def test_the_count_screen_gets_what_each_method_should_have(api, product, shift):
    _sell(api, product["id"])
    _sell(api, product["id"], "CREDIT_CARD", quantity=2)

    summary = api.get(f"/api/pos/shifts/{shift['id']}/cash-summary")

    assert summary["justificationThreshold"] == 1.0
    assert [(m["paymentMethod"], m["expected"]) for m in summary["byMethod"]] == [
        ("CASH", 111.5),
        ("CREDIT_CARD", 23.0),
    ]


def test_closing_keeps_the_numbered_z_with_the_count_of_each_method(
    api, product, shift
):
    _sell(api, product["id"])
    _sell(api, product["id"], "TRANSFER")

    closed = _close(
        api,
        shift["id"],
        _count("CASH", "111.50"),
        _count("TRANSFER", "11.50"),
        notes="Sin novedad",
    )

    assert closed["status"] == "CLOSED"
    assert closed["closingNumber"] == "Z-001-CAJA-01-000001"
    assert (closed["expectedBalance"], closed["closingBalance"]) == (111.5, 111.5)
    assert closed["closedBy"] == "Ana Cajera"
    z = _z(api, shift["id"])
    assert z["closing"]["number"] == "Z-001-CAJA-01-000001"
    assert z["closing"]["closedBy"] == "Ana Cajera"
    assert z["closing"]["notes"] == "Sin novedad"
    assert [
        (c["paymentMethod"], c["expected"], c["counted"], c["difference"])
        for c in z["closing"]["counts"]
    ] == [("CASH", 111.5, 111.5, 0), ("TRANSFER", 11.5, 11.5, 0)]
    assert z["salesSummary"]["count"] == 2
    assert z["shift"]["status"] == "CLOSED"
    # The history shows its number too
    [listed] = api.get("/api/pos/shifts", params={"terminalId": shift["terminalId"]})
    assert listed["closingNumber"] == "Z-001-CAJA-01-000001"


def test_every_method_the_shift_moved_must_be_counted(api, product, shift):
    _sell(api, product["id"], "TRANSFER")

    error = api.error(
        "POST",
        f"/api/pos/shifts/{shift['id']}/close",
        400,
        json={"counts": [_count("CASH", "100.00")]},
    )

    assert error["code"] == "CLOSING_COUNT_MISSING"
    assert api.get(f"/api/pos/shifts/{shift['id']}")["status"] == "OPEN"


def test_credit_is_not_counted(api, shift):
    error = api.error(
        "POST",
        f"/api/pos/shifts/{shift['id']}/close",
        400,
        json={"counts": [_count("CASH", "100.00"), _count("CREDIT", "0")]},
    )

    assert error["code"] == "CLOSING_COUNT_INVALID"


# Acceptance: a difference over the threshold needs a justification, audited


def test_a_difference_over_the_threshold_needs_a_justification_that_is_audited(
    api, admin_api, product, shift
):
    _sell(api, product["id"])

    error = api.error(
        "POST",
        f"/api/pos/shifts/{shift['id']}/close",
        400,
        json={"counts": [_count("CASH", "105.00")]},
    )
    assert error["code"] == "CLOSING_JUSTIFICATION_REQUIRED"
    assert api.get(f"/api/pos/shifts/{shift['id']}")["status"] == "OPEN"

    _close(api, shift["id"], _count("CASH", "105.00", "Billete falso retirado"))

    [count] = _z(api, shift["id"])["closing"]["counts"]
    assert (count["expected"], count["counted"], count["difference"]) == (
        111.5,
        105.0,
        -6.5,
    )
    assert count["justification"] == "Billete falso retirado"
    [entry] = admin_api.get("/api/admin/audit-log", params={"action": "shift.closed"})
    assert entry["resourceId"] == shift["id"]
    assert entry["after"]["closing_number"] == "Z-001-CAJA-01-000001"
    [audited] = entry["after"]["counts"]
    assert audited["justification"] == "Billete falso retirado"
    assert Decimal(audited["difference"]) == Decimal("-6.5")
    assert Decimal(entry["after"]["justification_threshold"]) == Decimal("1")


def test_a_difference_within_the_threshold_needs_none(api, shift):
    closed = _close(api, shift["id"], _count("CASH", "99.00"))

    assert closed["discrepancy"] == -1.0


def test_a_client_before_s5_9_closes_with_closing_balance(api, shift):
    closed = api.post(
        f"/api/pos/shifts/{shift['id']}/close", {"closingBalance": "100.00"}
    )

    assert closed["closingNumber"] == "Z-001-CAJA-01-000001"


# Acceptance: the Z of a closed shift doesn't change when its data does


def test_the_z_of_a_closed_shift_doesnt_change_when_its_data_does(
    api, product, shift, db_session
):
    cash_sale = _sell(api, product["id"])
    card_sale = _sell(api, product["id"], "CREDIT_CARD")
    _close(api, shift["id"], _count("CASH", "111.50"), _count("CREDIT_CARD", "11.50"))
    before = _z(api, shift["id"])

    # A sale of the shift is cancelled afterwards, and a payment is changed by hand
    api.post(f"/api/pos/sales/{cash_sale['id']}/cancel")
    db_session.execute(
        text("UPDATE payments SET amount = 999 WHERE sale_id = :id"),
        {"id": card_sale["id"]},
    )
    db_session.commit()

    # What the shift moved did change...
    x = api.get("/api/pos/reports/x-report", params={"shiftId": shift["id"]})
    assert x["salesSummary"]["count"] == 1
    assert [p["total"] for p in x["paymentsByMethod"]] == [999.0]
    # ...its Z closing didn't
    assert _z(api, shift["id"]) == before
    assert before["salesSummary"]["count"] == 2
    assert before["cashReconciliation"]["cashSales"] == 11.5


# Nothing enters a closed shift


def test_a_closed_shift_takes_no_more_documents(api, manager, product, shift):
    sale = _sell(api, product["id"])
    [item] = api.get(f"/api/pos/sales/{sale['id']}/items")
    refund = api.post(
        "/api/pos/refunds",
        {
            "originalSaleId": sale["id"],
            "items": [{"saleItemId": item["id"], "quantity": 1}],
        },
    )
    parked = api.post("/api/pos/sales", {"isFinalConsumer": True})
    api.post(
        f"/api/pos/sales/{parked['id']}/items",
        {"productId": product["id"], "quantity": 1},
    )
    api.post(
        f"/api/pos/sales/{parked['id']}/payments",
        {"amount": "11.50", "paymentMethod": "CASH"},
    )
    _close(api, shift["id"], _count("CASH", "111.50"))
    z = _z(api, shift["id"])

    refused = [
        manager.error(
            "POST",
            f"/api/pos/refunds/{refund['id']}/process",
            400,
            json={"payments": [{"amount": "11.50", "paymentMethod": "CASH"}]},
        ),
        api.error("POST", f"/api/pos/sales/{parked['id']}/confirm", 400),
        api.error(
            "POST",
            f"/api/pos/shifts/{shift['id']}/cash-movements",
            400,
            json={"type": "OUT", "amount": "5.00", "reason": "Retiro"},
        ),
        api.error(
            "POST",
            "/api/pos/sales/quick",
            400,
            json={
                "items": [{"productId": product["id"], "quantity": 1}],
                "payments": [{"amount": "11.50", "paymentMethod": "CASH"}],
            },
        ),
    ]

    assert [e["code"] for e in refused] == [
        "NO_OPEN_SHIFT",
        "NO_OPEN_SHIFT",
        "SHIFT_NOT_OPEN_FOR_CASH_MOVEMENT",
        "NO_OPEN_SHIFT",
    ]
    assert _z(api, shift["id"]) == z


def _checkout(headers: dict[str, str], product_id: int):
    return lambda client: client.post(
        "/api/pos/sales/quick",
        json={
            "items": [{"productId": product_id, "quantity": 1}],
            "payments": [{"amount": "11.50", "paymentMethod": "CASH"}],
        },
        headers=with_key(headers),
    )


def test_a_checkout_waits_for_the_closing_and_finds_the_shift_closed(
    pg_engine: Engine, api, product, shift
):
    """The closing holds the shift FOR UPDATE: a checkout waits for it and, once
    it commits, reads the shift again and finds it closed"""
    responses: list[Response] = []
    with pg_engine.connect() as closing:
        transaction = closing.begin()
        closing.execute(
            text("SELECT id FROM pos_shifts WHERE id = :id FOR UPDATE"),
            {"id": shift["id"]},
        )
        checkout = threading.Thread(
            target=lambda: responses.append(
                _checkout(api.headers, product["id"])(TestClient(app))
            )
        )
        checkout.start()
        checkout.join(timeout=2)
        assert checkout.is_alive(), "the checkout didn't wait for the closing"
        closing.execute(
            text("UPDATE pos_shifts SET status = 'CLOSED' WHERE id = :id"),
            {"id": shift["id"]},
        )
        transaction.commit()
    checkout.join(timeout=30)

    [response] = responses
    assert response.status_code == 400, response.text
    assert response.json()["errors"][0]["code"] == "NO_OPEN_SHIFT"


def test_a_sale_and_the_closing_at_once_never_leave_the_sale_out_of_the_z(
    api, product, shift
):
    responses = concurrently(
        _checkout(api.headers, product["id"]),
        lambda client: client.post(
            f"/api/pos/shifts/{shift['id']}/close",
            json={"counts": [_count("CASH", "100.00", "Venta en curso al cerrar")]},
            headers=api.headers,
        ),
    )

    statuses = {r.request.url.path: r.status_code for r in responses}
    assert statuses[f"/api/pos/shifts/{shift['id']}/close"] == 200
    sold = statuses["/api/pos/sales/quick"] == 201
    assert sold or statuses["/api/pos/sales/quick"] == 400
    z = _z(api, shift["id"])
    assert z["salesSummary"]["count"] == (1 if sold else 0)
    assert z["closing"]["counts"][0]["expected"] == (111.5 if sold else 100.0)


# The correlative per terminal


def test_the_z_number_is_a_correlative_of_each_terminal(
    client, admin_api, api, cashier, shelf
):
    numbers = []
    for _ in range(2):
        opened = api.post("/api/pos/shifts/open", {"openingBalance": "0"})
        numbers.append(_close(api, opened["id"], _count("CASH", "0"))["closingNumber"])
    second = Api(
        client,
        at_terminal(cashier, make_terminal(admin_api, shelf["id"], code="CAJA-02")),
    )
    opened = second.post("/api/pos/shifts/open", {"openingBalance": "0"})
    numbers.append(_close(second, opened["id"], _count("CASH", "0"))["closingNumber"])

    assert numbers == [
        "Z-001-CAJA-01-000001",
        "Z-001-CAJA-01-000002",
        "Z-001-CAJA-02-000001",
    ]


# The application can't change a closing


@pytest.fixture
def app_session(pg_engine, tenant):
    """A session of faclab_app inside the tenant, as a request has"""
    factory = create_session_maker(os.environ["DATABASE_URL"])
    with use_tenant(TenantContext(tenant, TenantSource.TASK)), factory() as session:
        yield session
    factory.kw["bind"].dispose()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE pos_shift_closings SET sales_total = 0",
        "DELETE FROM pos_shift_closings",
        "UPDATE pos_shift_closing_lines SET counted = 0",
        "DELETE FROM pos_shift_closing_lines",
    ],
    ids=["update", "delete", "update-line", "delete-line"],
)
def test_the_app_cant_change_nor_delete_a_closing(api, shift, app_session, statement):
    _close(api, shift["id"], _count("CASH", "100.00"))

    with pytest.raises(ProgrammingError) as error:
        app_session.execute(text(statement))

    assert getattr(error.value.orig, "pgcode", None) == INSUFFICIENT_PRIVILEGE


def test_only_inserting_and_reading_closings_are_granted(pg_engine):
    with pg_engine.connect() as conn:
        granted = {
            (table, role, privilege)
            for table in ("pos_shift_closings", "pos_shift_closing_lines")
            for role in ("faclab_app", "faclab_worker")
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
            if conn.execute(
                text("SELECT has_table_privilege(:role, :table, :privilege)"),
                {"role": role, "table": table, "privilege": privilege},
            ).scalar_one()
        }

    assert granted == {
        (table, role, privilege)
        for table in ("pos_shift_closings", "pos_shift_closing_lines")
        for role in ("faclab_app", "faclab_worker")
        for privilege in ("SELECT", "INSERT")
    }
