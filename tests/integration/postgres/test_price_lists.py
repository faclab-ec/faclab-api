"""Price lists against PostgreSQL (S5.3): a hardware store sells cement to the
public at 9.50 and to builders at their wholesale list's price, with a volume
price from 50 bags; a product without a price in the list takes the general
one."""

import subprocess
import sys
from uuid import UUID

import pytest
from sqlalchemy import Engine, inspect, text

from src.auth.domain.entities import Role
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    make_customer,
    make_location,
    make_movement,
    make_presentation,
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
def cashier(client, auth_headers, terminal) -> Api:
    """A cashier at terminal CAJA-01 of branch 001, with its shift open"""
    api = Api(client, at_terminal(auth_headers(Role.CASHIER), terminal))
    api.post("/api/pos/shifts/open", {"openingBalance": "0"})
    return api


@pytest.fixture
def cement(admin_api, shelf) -> dict:
    """Cement at 9.50 a bag, with a pallet of 40 bags and stock for both"""
    product = make_product(admin_api, "FERR-003", name="Cemento", salePrice="9.50")
    pallet = make_presentation(admin_api, product["id"], "Pallet x40", 40)
    make_movement(admin_api, product["id"], 500, shelf["id"])
    return {**product, "pallet": pallet}


@pytest.fixture
def nails(admin_api, shelf) -> dict:
    product = make_product(admin_api, "FERR-010", name="Clavos", salePrice="2.00")
    make_movement(admin_api, product["id"], 100, shelf["id"])
    return product


@pytest.fixture
def wholesale(admin_api, cement) -> dict:
    """Builders pay 8.90 a bag and 8.50 from 50 bags"""
    price_list = admin_api.post(
        "/api/admin/price-lists",
        {"name": "Mayorista", "description": "Maestros y constructores"},
    )
    path = f"/api/admin/price-lists/{price_list['id']}/items"
    admin_api.post(path, {"productId": cement["id"], "price": "8.90"})
    admin_api.post(
        path, {"productId": cement["id"], "price": "8.50", "minQuantity": 50}
    )
    return price_list


@pytest.fixture
def builder(admin_api, wholesale) -> dict:
    customer = make_customer(admin_api, seed=7, name="Ferretería El Maestro")
    return admin_api.put(
        f"/api/admin/customers/{customer['id']}/price-list",
        {"priceListId": wholesale["id"]},
    )


def _resolve(cashier: Api, customer: dict | None, *lines: dict) -> list[dict]:
    return cashier.post(
        "/api/pos/prices/resolve",
        {"customerId": customer["id"] if customer else None, "items": list(lines)},
    )


def _quick_sale(cashier: Api, customer: dict | None, line: dict, amount: str):
    return cashier.post(
        "/api/pos/sales/quick",
        {
            "customerId": customer["id"] if customer else None,
            "items": [line],
            "payments": [{"amount": amount, "paymentMethod": "CASH"}],
        },
    )


def test_a_wholesale_customer_gets_the_price_of_its_list(cashier, cement, builder):
    """Acceptance: the builder's list price, and from 50 bags the volume one"""
    [few, many] = _resolve(
        cashier,
        builder,
        {"productId": cement["id"], "quantity": 10},
        {"productId": cement["id"], "quantity": 60},
    )

    assert (few["unitPrice"], few["priceListName"]) == (8.9, "Mayorista")
    assert (many["unitPrice"], many["minQuantity"]) == (8.5, 50)

    # Sold without a price: 60 × 8.50 = 510.00 + VAT 76.50
    sale = _quick_sale(
        cashier, builder, {"productId": cement["id"], "quantity": 60}, "586.50"
    )
    [line] = cashier.get(f"/api/pos/sales/{sale['id']}/items")
    assert (line["unitPrice"], line["priceOverride"]) == (8.5, None)
    assert sale["total"] == 586.5


def test_a_product_without_a_price_in_the_list_takes_the_general_one(
    cashier, cement, nails, builder
):
    """Acceptance: the nails aren't in the wholesale list"""
    [line] = _resolve(cashier, builder, {"productId": nails["id"], "quantity": 3})

    assert (line["unitPrice"], line["priceListId"]) == (2.0, None)


def test_the_public_pays_the_general_price_with_its_tiers(
    admin_api, cashier, cement, tenant, pg_engine
):
    """The general list holds a tier for everyone: 9.00 from 10 bags"""
    general = _general_list(pg_engine, tenant)
    admin_api.post(
        f"/api/admin/price-lists/{general}/items",
        {"productId": cement["id"], "price": "9.00", "minQuantity": 10},
    )

    [few, many] = _resolve(
        cashier,
        None,
        {"productId": cement["id"], "quantity": 9},
        {"productId": cement["id"], "quantity": 10},
    )

    assert few["unitPrice"] == 9.5
    assert (many["unitPrice"], many["priceListName"]) == (9.0, "General")
    # Its base price is the product's: it only takes tiers
    error = admin_api.error(
        "POST",
        f"/api/admin/price-lists/{general}/items",
        400,
        json={"productId": cement["id"], "price": "9.20"},
    )
    assert error["code"] == "DEFAULT_PRICE_LIST_BASE_PRICE"


def test_the_branchs_list_prices_a_customer_without_one(
    admin_api, cashier, terminal, cement
):
    branch_list = admin_api.post("/api/admin/price-lists", {"name": "Sucursal Norte"})
    admin_api.post(
        f"/api/admin/price-lists/{branch_list['id']}/items",
        {"productId": cement["id"], "price": "9.20"},
    )
    branch = admin_api.get(f"/api/admin/branches/{terminal['branchId']}")
    admin_api.put(
        f"/api/admin/branches/{branch['id']}",
        {
            "establishmentCode": branch["establishmentCode"],
            "name": branch["name"],
            "priceListId": branch_list["id"],
        },
    )
    walk_in = make_customer(admin_api, seed=8, name="Cliente de paso")

    [line] = _resolve(cashier, walk_in, {"productId": cement["id"], "quantity": 1})

    assert (line["unitPrice"], line["priceListName"]) == (9.2, "Sucursal Norte")


def test_a_pallet_takes_its_lists_bag_price_times_40(cashier, cement, builder):
    # 2 pallets are 80 bags: the tier from 50 bags, × 40
    [line] = _resolve(
        cashier,
        builder,
        {
            "productId": cement["id"],
            "presentationId": cement["pallet"]["id"],
            "quantity": 2,
        },
    )

    assert line["unitPrice"] == 340.0  # 40 × 8.50


def test_another_price_needs_a_reason_and_is_audited(
    admin_api, cashier, cement, builder
):
    """The manual change keeps asking for its reason, also on an added item"""
    draft = cashier.post("/api/pos/sales", {"customerId": builder["id"]})
    path = f"/api/pos/sales/{draft['id']}/items"

    error = cashier.error(
        "POST",
        path,
        400,
        json={"productId": cement["id"], "quantity": 1, "unitPrice": "9.50"},
    )
    assert error["code"] == "OVERRIDE_REASON_REQUIRED"

    item = cashier.post(
        path,
        {
            "productId": cement["id"],
            "quantity": 1,
            "unitPrice": "8.00",
            "overrideReason": "Saco roto",
        },
    )
    assert (item["unitPrice"], item["priceOverride"]) == (8.0, 8.0)
    [entry] = admin_api.get(
        "/api/admin/audit-log", params={"action": "sale.price_overridden"}
    )
    assert entry["before"] == {"unit_price": "8.900000"}
    assert entry["after"]["reason"] == "Saco roto"


def test_a_new_quantity_reaches_the_volume_price(cashier, cement, builder):
    draft = cashier.post("/api/pos/sales", {"customerId": builder["id"]})
    item = cashier.post(
        f"/api/pos/sales/{draft['id']}/items",
        {"productId": cement["id"], "quantity": 10},
    )
    assert item["unitPrice"] == 8.9

    updated = cashier.put(
        f"/api/pos/sales/{draft['id']}/items/{item['id']}", {"quantity": 50}
    )

    assert updated["unitPrice"] == 8.5


def test_an_assigned_list_cant_be_deleted(admin_api, wholesale, builder):
    error = admin_api.error("DELETE", f"/api/admin/price-lists/{wholesale['id']}", 409)

    assert error["code"] == "RECORD_IN_USE"


def test_an_inactive_list_prices_nothing(
    admin_api, cashier, cement, wholesale, builder
):
    admin_api.put(
        f"/api/admin/price-lists/{wholesale['id']}",
        {"name": "Mayorista", "isActive": False},
    )

    [line] = _resolve(cashier, builder, {"productId": cement["id"], "quantity": 1})

    assert line["unitPrice"] == 9.5


def test_a_cashier_cant_give_a_customer_a_list(
    client, auth_headers, terminal, admin_api, wholesale
):
    """Cashiers edit customers, but a customer's list changes its prices"""
    cashier = Api(client, at_terminal(auth_headers(Role.CASHIER), terminal))
    customer = make_customer(admin_api, seed=9, name="Cliente")

    error = cashier.error(
        "PUT",
        f"/api/admin/customers/{customer['id']}/price-list",
        403,
        json={"priceListId": wholesale["id"]},
    )

    assert error["code"] == "PERMISSION_DENIED"


def _general_list(engine: Engine, tenant: UUID) -> int:
    """The tenant's general list, as provisioning leaves it (the test tenants are
    inserted directly)"""
    with engine.begin() as conn:
        found = conn.execute(
            text("SELECT id FROM price_lists WHERE tenant_id = :t AND is_default"),
            {"t": tenant},
        ).scalar()
        if found is not None:
            return found
        return conn.execute(
            text(
                "INSERT INTO price_lists (tenant_id, name, is_default, is_active, "
                "created_at) VALUES (:t, 'General', true, true, now()) RETURNING id"
            ),
            {"t": tenant},
        ).scalar_one()


def _alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_the_migration_gives_every_company_its_general_list(pg_engine, tenant):
    down = _alembic("downgrade", "f6c2d84e1a97")
    assert down.returncode == 0, down.stderr
    assert "price_lists" not in inspect(pg_engine).get_table_names()

    up = _alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr

    with pg_engine.connect() as conn:
        lists = conn.execute(
            text("SELECT name, is_default FROM price_lists WHERE tenant_id = :t"),
            {"t": tenant},
        ).all()
    assert lists == [("General", True)]
