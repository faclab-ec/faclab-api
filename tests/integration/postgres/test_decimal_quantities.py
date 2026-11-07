"""Decimal quantities against PostgreSQL (S5.1): a hardware store sells 2.5 m of
cable from the POS and the stock goes down 2.5; a unit without decimals rejects
1.5; the migration doesn't go back to integers while a fraction is stored."""

import subprocess
import sys

import pytest
from sqlalchemy import inspect

from src.auth.domain.entities import Role
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    make_location,
    make_movement,
    make_product,
    make_terminal,
    make_warehouse,
)
from tests.integration.postgres.support import ROOT


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def shelf(admin_api) -> dict:
    return make_location(admin_api, make_warehouse(admin_api)["id"])


@pytest.fixture
def terminal(admin_api, shelf) -> dict:
    return make_terminal(admin_api, shelf["id"])


@pytest.fixture
def api(client, auth_headers, terminal) -> Api:
    """A cashier at terminal CAJA-01 of branch 001, with its shift open"""
    cashier = Api(client, at_terminal(auth_headers(Role.CASHIER), terminal))
    cashier.post("/api/pos/shifts/open", {"openingBalance": "0"})
    return cashier


@pytest.fixture
def manager(client, auth_headers, terminal) -> Api:
    """Processes the refunds at the same terminal"""
    return Api(client, at_terminal(auth_headers(Role.MANAGER), terminal))


def _unit(admin_api: Api, symbol: str, decimals: int) -> dict:
    return admin_api.post(
        "/api/admin/units-of-measure",
        {"name": f"Unit {symbol}", "symbol": symbol, "decimals": decimals},
    )


@pytest.fixture
def cable(admin_api, shelf) -> dict:
    """Cable sold by the meter (2 decimals) at 0.85, VAT 15%, 10 m on the shelf"""
    meter = _unit(admin_api, "m", 2)
    product = make_product(
        admin_api,
        "CAB-12",
        salePrice="0.85",
        unitOfMeasureId=meter["id"],
    )
    make_movement(admin_api, product["id"], 10, shelf["id"])
    return product


def _stock(admin_api: Api, product_id: int) -> float:
    rows = admin_api.get("/api/admin/stock", params={"productId": product_id})
    return sum(row["quantity"] for row in rows)


def _quick_sale(api: Api, product_id: int, quantity, amount: str) -> dict:
    return api.post(
        "/api/pos/sales/quick",
        {
            "items": [{"productId": product_id, "quantity": quantity}],
            "payments": [{"amount": amount, "paymentMethod": "CASH"}],
        },
    )


def test_the_pos_sells_and_refunds_meters_of_cable(api, manager, admin_api, cable):
    product = api.get(f"/api/pos/products/{cable['id']}")
    assert (product["unitSymbol"], product["quantityDecimals"]) == ("m", 2)

    # 2.5 × 0.85 = 2.125 → 2.13; VAT 0.31875 → 0.32
    sale = _quick_sale(api, cable["id"], 2.5, "2.45")

    assert (sale["subtotal"], sale["tax"], sale["total"]) == (2.13, 0.32, 2.45)
    assert _stock(admin_api, cable["id"]) == 7.5
    [item] = api.get(f"/api/pos/sales/{sale['id']}/items")
    assert item["quantity"] == 2.5
    receipt = api.get(f"/api/pos/sales/{sale['id']}/receipt")
    assert receipt["items"][0]["quantity"] == 2.5

    # A string is read too, as the API reads money
    refund = api.post(
        "/api/pos/refunds",
        {
            "originalSaleId": sale["id"],
            "items": [{"saleItemId": item["id"], "quantity": "1.25"}],
        },
    )
    # 1.25 × 0.85 = 1.0625 → 1.06; VAT 0.159375 → 0.16
    assert refund["total"] == 1.22
    manager.post(
        f"/api/pos/refunds/{refund['id']}/process",
        {"payments": [{"amount": "1.22", "paymentMethod": "CASH"}]},
    )
    assert _stock(admin_api, cable["id"]) == 8.75

    movements = admin_api.get("/api/admin/movements", params={"productId": cable["id"]})
    assert sorted(m["quantity"] for m in movements) == [-2.5, 1.25, 10]


def test_a_unit_without_decimals_rejects_a_fraction(api, admin_api, shelf):
    unit = _unit(admin_api, "und", 0)
    hammer = make_product(admin_api, "MAR-16", unitOfMeasureId=unit["id"])
    make_movement(admin_api, hammer["id"], 5, shelf["id"])

    error = api.error(
        "POST",
        "/api/pos/sales/quick",
        422,
        json={
            "items": [{"productId": hammer["id"], "quantity": 1.5}],
            "payments": [{"amount": "17.25", "paymentMethod": "CASH"}],
        },
    )

    assert error["code"] == "QUANTITY_PRECISION_EXCEEDED"
    assert admin_api.get("/api/admin/sales") == []
    assert _stock(admin_api, hammer["id"]) == 5
    # Nor a manual movement, nor a product without unit
    for product_id in (hammer["id"], make_product(admin_api, "SIN-1")["id"]):
        error = admin_api.error(
            "POST",
            "/api/admin/movements",
            422,
            json={
                "productId": product_id,
                "quantity": 1.5,
                "type": "IN",
                "locationId": shelf["id"],
            },
        )
        assert error["code"] == "QUANTITY_PRECISION_EXCEEDED"


def test_more_than_six_decimals_is_rejected_by_the_api(api, admin_api, cable):
    error = api.error(
        "POST",
        "/api/pos/sales/quick",
        422,
        json={
            "items": [{"productId": cable["id"], "quantity": "1.1234567"}],
            "payments": [{"amount": "2.00", "paymentMethod": "CASH"}],
        },
    )

    assert error["code"] == "VALIDATION_ERROR"


def _alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_the_migration_keeps_fractions_from_being_rounded(
    admin_api, pg_engine, shelf, cable
):
    """7.5 m in stock: going back to integer quantities would round it"""
    make_movement(admin_api, cable["id"], -2.5, shelf["id"])

    down = _alembic("downgrade", "d8e4f2a1b6c3")

    assert down.returncode != 0
    assert "holds a fractional quantity" in down.stderr
    columns = {c["name"] for c in inspect(pg_engine).get_columns("units_of_measure")}
    assert "decimals" in columns
