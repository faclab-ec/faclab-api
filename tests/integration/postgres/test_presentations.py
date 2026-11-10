"""Presentations against PostgreSQL (S5.2): a hardware store buys screws in boxes
of 100 and sells them by the unit or by the box. Stock is always kept in base
units; scanning the box's barcode sells the box at its price."""

import subprocess
import sys

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import config
from src.auth.domain.entities import Role
from src.shared.infra.outbox.models import OutboxMessageModel
from tests.contract.contracts import errors, validator
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    make_location,
    make_presentation,
    make_product,
    make_supplier,
    make_terminal,
    make_warehouse,
    unit_id,
)
from tests.integration.postgres.support import ROOT

BOX_BARCODE = "7861000001001"


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
def manager(client, auth_headers, terminal) -> Api:
    """Processes the refunds at the same terminal"""
    return Api(client, at_terminal(auth_headers(Role.MANAGER), terminal))


@pytest.fixture
def screw(admin_api) -> dict:
    """Screws by the unit at 0.05 (cost 0.03), VAT 15%, and a box of 100 with its
    own barcode and price (4.50 instead of 5.00)"""
    product = make_product(
        admin_api,
        "TOR-1",
        name="Tornillo 1/2",
        purchasePrice="0.03",
        salePrice="0.05",
        barcode="7861000001000",
    )
    box = make_presentation(
        admin_api,
        product["id"],
        "Caja x100",
        100,
        barcode=BOX_BARCODE,
        salePrice="4.50",
    )
    return {**product, "box": box}


def _stock(admin_api: Api, product_id: int) -> float:
    rows = admin_api.get("/api/admin/stock", params={"productId": product_id})
    return sum(row["quantity"] for row in rows)


def _buy(admin_api: Api, product_id: int, presentation_id: int, quantity, shelf):
    """A purchase order of `quantity` presentations, sent and fully received"""
    supplier = make_supplier(admin_api)
    po = admin_api.post("/api/admin/purchase-orders", {"supplierId": supplier["id"]})
    item = admin_api.post(
        "/api/admin/purchase-order-items",
        {
            "purchaseOrderId": po["id"],
            "productId": product_id,
            "presentationId": presentation_id,
            "quantityOrdered": quantity,
            "unitCost": "3.00",
        },
    )
    admin_api.post(f"/api/admin/purchase-orders/{po['id']}/send")
    admin_api.post(
        f"/api/admin/purchase-orders/{po['id']}/receive",
        {
            "items": [
                {
                    "purchaseOrderItemId": item["id"],
                    "quantityReceived": quantity,
                    "locationId": shelf["id"],
                }
            ]
        },
    )
    return po, item


def _quick_sale(cashier: Api, line: dict, amount: str) -> dict:
    return cashier.post(
        "/api/pos/sales/quick",
        {
            "items": [line],
            "payments": [{"amount": amount, "paymentMethod": "CASH"}],
        },
    )


def test_buying_two_boxes_and_selling_fifteen_units(admin_api, cashier, shelf, screw):
    """Acceptance: 2 boxes of 100 add 200 base units; 15 units take 15"""
    po, item = _buy(admin_api, screw["id"], screw["box"]["id"], 2, shelf)

    assert _stock(admin_api, screw["id"]) == 200
    [line] = admin_api.get(f"/api/admin/purchase-orders/{po['id']}/items")
    assert (line["presentationName"], line["unitFactor"]) == ("Caja x100", 100)
    assert (line["quantityOrdered"], line["quantityReceived"]) == (2, 2)
    assert admin_api.get(f"/api/admin/purchase-orders/{po['id']}")["status"] == (
        "received"
    )

    # 15 × 0.05 = 0.75; VAT 0.1125 → 0.11
    sale = _quick_sale(cashier, {"productId": screw["id"], "quantity": 15}, "0.86")

    assert sale["total"] == 0.86
    assert _stock(admin_api, screw["id"]) == 185
    [sold] = cashier.get(f"/api/pos/sales/{sale['id']}/items")
    assert (sold["presentationName"], sold["quantity"], sold["baseQuantity"]) == (
        "Unidad",
        15,
        15,
    )
    movements = admin_api.get("/api/admin/movements", params={"productId": screw["id"]})
    assert sorted(m["quantity"] for m in movements) == [-15, 200]


def test_scanning_the_box_sells_the_box_at_its_price(admin_api, cashier, shelf, screw):
    """Acceptance: the box's barcode adds the box presentation with its price"""
    _buy(admin_api, screw["id"], screw["box"]["id"], 2, shelf)

    found = cashier.get("/api/pos/products/barcode", params={"code": BOX_BARCODE})

    assert found["product"]["id"] == screw["id"]
    box = found["presentation"]
    assert (box["id"], box["name"], box["factor"]) == (
        screw["box"]["id"],
        "Caja x100",
        100,
    )
    assert box["effectiveSalePrice"] == 4.5
    # The search finds it by that barcode too
    [hit] = cashier.get("/api/pos/products/search", params={"term": BOX_BARCODE})
    assert hit["id"] == screw["id"]

    # Sold without a price: the box's. 4.50 + VAT 0.675 → 5.18
    sale = _quick_sale(
        cashier,
        {"productId": screw["id"], "presentationId": box["id"], "quantity": 1},
        "5.18",
    )

    assert (sale["subtotal"], sale["total"]) == (4.5, 5.18)
    [item] = sale["items"]
    assert (item["unitPrice"], item["priceOverride"]) == (4.5, None)
    assert _stock(admin_api, screw["id"]) == 100
    receipt = cashier.get(f"/api/pos/sales/{sale['id']}/receipt")
    assert [
        (i["presentationName"], i["quantity"], i["baseQuantity"])
        for i in receipt["items"]
    ] == [("Caja x100", 1, 100)]


def test_a_box_without_its_own_price_sells_at_factor_times_the_unit(
    admin_api, cashier, shelf, screw
):
    pack = make_presentation(admin_api, screw["id"], "Paquete x10", 10)
    assert pack["effectiveSalePrice"] == 0.5
    _buy(admin_api, screw["id"], screw["box"]["id"], 1, shelf)

    # 2 × 0.50 = 1.00; VAT 0.15
    sale = _quick_sale(
        cashier,
        {"productId": screw["id"], "presentationId": pack["id"], "quantity": 2},
        "1.15",
    )

    assert sale["total"] == 1.15
    assert _stock(admin_api, screw["id"]) == 80


def test_another_price_for_the_box_needs_a_reason(admin_api, cashier, shelf, screw):
    _buy(admin_api, screw["id"], screw["box"]["id"], 1, shelf)
    line = {
        "productId": screw["id"],
        "presentationId": screw["box"]["id"],
        "quantity": 1,
    }

    error = cashier.error(
        "POST",
        "/api/pos/sales/quick",
        400,
        json={
            "items": [{**line, "unitPrice": "4.00"}],
            "payments": [{"amount": "4.60", "paymentMethod": "CASH"}],
        },
    )

    assert error["code"] == "OVERRIDE_REASON_REQUIRED"


def test_refunding_the_box_puts_back_its_units(
    admin_api, cashier, manager, shelf, screw
):
    _buy(admin_api, screw["id"], screw["box"]["id"], 2, shelf)
    sale = _quick_sale(
        cashier,
        {"productId": screw["id"], "presentationId": screw["box"]["id"], "quantity": 2},
        "10.35",
    )
    [item] = cashier.get(f"/api/pos/sales/{sale['id']}/items")
    assert _stock(admin_api, screw["id"]) == 0

    refund = cashier.post(
        "/api/pos/refunds",
        {
            "originalSaleId": sale["id"],
            "items": [{"saleItemId": item["id"], "quantity": 1}],
        },
    )
    [refunded] = refund["items"]
    assert (refunded["quantity"], refunded["baseQuantity"]) == (1, 100)
    manager.post(
        f"/api/pos/refunds/{refund['id']}/process",
        {"payments": [{"amount": "5.18", "paymentMethod": "CASH"}]},
    )

    assert _stock(admin_api, screw["id"]) == 100


def test_half_a_box_of_whole_units_is_rejected(admin_api, cashier, shelf, screw):
    _buy(admin_api, screw["id"], screw["box"]["id"], 1, shelf)

    error = cashier.error(
        "POST",
        "/api/pos/sales/quick",
        422,
        json={
            "items": [
                {
                    "productId": screw["id"],
                    "presentationId": screw["box"]["id"],
                    "quantity": 0.5,
                }
            ],
            "payments": [{"amount": "2.59", "paymentMethod": "CASH"}],
        },
    )

    assert error["code"] == "QUANTITY_PRECISION_EXCEEDED"


@pytest.mark.parametrize("factor", [0, -1])
def test_the_factor_cant_be_zero_or_negative(admin_api, screw, factor):
    """Acceptance: the conversion factor is greater than zero"""
    error = admin_api.error(
        "POST",
        f"/api/admin/products/{screw['id']}/presentations",
        422,
        json={"name": "Caja", "factor": factor},
    )

    assert error["code"] == "VALIDATION_ERROR"


def test_the_database_rejects_a_factor_of_zero(pg_engine, screw):
    rejected = pytest.raises(IntegrityError, match="ck_product_presentations_factor")
    with rejected, pg_engine.begin() as conn:
        conn.execute(
            text("UPDATE product_presentations SET factor = 0 WHERE id = :id"),
            {"id": screw["box"]["id"]},
        )


def test_a_barcode_is_unique_among_every_presentation(admin_api, screw):
    other = make_product(admin_api, "CLA-1")

    for path, body in (
        (
            f"/api/admin/products/{other['id']}/presentations",
            {"name": "Caja", "factor": 50, "barcode": BOX_BARCODE},
        ),
        (
            "/api/admin/products",
            {
                "name": "Clavo",
                "sku": "CLA-2",
                "unitOfMeasureId": unit_id(admin_api),
                "barcode": screw["barcode"],
            },
        ),
    ):
        error = admin_api.error("POST", path, 409, json=body)
        assert error["code"] == "PRODUCT_BARCODE_ALREADY_EXISTS"


def test_the_base_presentation_is_the_unit(admin_api, screw):
    [base, box] = admin_api.get(f"/api/admin/products/{screw['id']}/presentations")
    assert (base["isBase"], base["name"], base["factor"]) == (True, "Unidad", 1)
    assert base["barcode"] == screw["barcode"] == "7861000001000"
    assert base["effectiveSalePrice"] == 0.05
    assert box["id"] == screw["box"]["id"]

    error = admin_api.error(
        "PUT",
        f"/api/admin/products/{screw['id']}/presentations/{base['id']}",
        400,
        json={"name": "Unidad", "factor": 2},
    )
    assert error["code"] == "BASE_PRESENTATION_FIXED"
    admin_api.error(
        "DELETE",
        f"/api/admin/products/{screw['id']}/presentations/{base['id']}",
        400,
    )
    # Its barcode is the product's
    admin_api.put(
        f"/api/admin/products/{screw['id']}/presentations/{base['id']}",
        {"name": "Unidad", "factor": 1, "barcode": "7861000001999"},
    )
    assert admin_api.get(f"/api/admin/products/{screw['id']}")["barcode"] == (
        "7861000001999"
    )


def test_the_base_follows_the_unit_of_the_product(admin_api, screw):
    meters = unit_id(admin_api, "m", "Metro", 2)
    admin_api.put(
        f"/api/admin/products/{screw['id']}",
        {"name": screw["name"], "sku": screw["sku"], "unitOfMeasureId": meters},
    )

    product = admin_api.get(f"/api/admin/products/{screw['id']}")
    assert product["barcode"] is None
    assert [p["name"] for p in product["presentations"]] == ["Metro", "Caja x100"]


def test_a_presentation_in_use_is_deactivated_instead_of_deleted(
    admin_api, cashier, shelf, screw
):
    _buy(admin_api, screw["id"], screw["box"]["id"], 1, shelf)
    path = f"/api/admin/products/{screw['id']}/presentations/{screw['box']['id']}"

    error = admin_api.error("DELETE", path, 409)
    assert error["code"] == "RECORD_IN_USE"

    admin_api.put(
        path,
        {"name": "Caja x100", "factor": 100, "barcode": BOX_BARCODE, "isActive": False},
    )
    error = cashier.error(
        "POST",
        "/api/pos/sales/quick",
        400,
        json={
            "items": [
                {
                    "productId": screw["id"],
                    "presentationId": screw["box"]["id"],
                    "quantity": 1,
                }
            ],
            "payments": [{"amount": "5.18", "paymentMethod": "CASH"}],
        },
    )
    assert error["code"] == "PRESENTATION_INACTIVE"
    cashier.error("GET", "/api/pos/products/barcode", 404, params={"code": BOX_BARCODE})


def test_a_presentation_of_another_product_is_not_found(admin_api, cashier, screw):
    other = make_product(admin_api, "CLA-1")

    error = cashier.error(
        "POST",
        "/api/pos/sales/quick",
        404,
        json={
            "items": [
                {
                    "productId": other["id"],
                    "presentationId": screw["box"]["id"],
                    "quantity": 1,
                }
            ],
            "payments": [{"amount": "11.50", "paymentMethod": "CASH"}],
        },
    )

    assert error["code"] == "NOT_FOUND"


def test_the_invoice_names_the_box(
    admin_api, cashier, shelf, screw, db_session: Session, monkeypatch
):
    """Quantity and price of the box; its name in the line's description"""
    monkeypatch.setattr(config, "KAFKA_ENABLED", True)
    _buy(admin_api, screw["id"], screw["box"]["id"], 2, shelf)

    cashier.post(
        "/api/pos/sales/quick",
        {
            "items": [
                {"productId": screw["id"], "quantity": 2},
                {
                    "productId": screw["id"],
                    "presentationId": screw["box"]["id"],
                    "quantity": 1,
                },
            ],
            "payments": [{"amount": "5.29", "paymentMethod": "CASH"}],
        },
    )

    [message] = db_session.scalars(select(OutboxMessageModel))
    assert errors(validator("sales.confirmed", 3), message.payload) == []
    assert [
        (i["product_name"], i["quantity"], i["unit_price"])
        for i in message.payload["payload"]["items"]
    ] == [
        ("Tornillo 1/2", "2", "0.050000"),
        ("Tornillo 1/2 (Caja x100)", "1", "4.500000"),
    ]


def test_the_x_report_counts_base_units(admin_api, cashier, shelf, screw):
    _buy(admin_api, screw["id"], screw["box"]["id"], 2, shelf)
    _quick_sale(cashier, {"productId": screw["id"], "quantity": 15}, "0.86")
    sale = _quick_sale(
        cashier,
        {"productId": screw["id"], "presentationId": screw["box"]["id"], "quantity": 1},
        "5.18",
    )
    shift_id = cashier.get(f"/api/pos/sales/{sale['id']}")["shiftId"]

    report = cashier.get("/api/pos/reports/x-report", params={"shiftId": shift_id})

    [line] = report["itemsSold"]
    assert line["quantity"] == 115


def _alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_the_migration_keeps_boxes_from_being_read_as_units(
    admin_api, pg_engine, shelf, screw
):
    _buy(admin_api, screw["id"], screw["box"]["id"], 2, shelf)

    down = _alembic("downgrade", "e3b7a91c5d20")

    assert down.returncode != 0
    assert "holds lines in a presentation" in down.stderr
    columns = {c["name"] for c in inspect(pg_engine).get_columns("sale_items")}
    assert "base_quantity" in columns
