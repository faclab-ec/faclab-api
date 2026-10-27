"""Inventory flows against PostgreSQL: movements, stock, adjustments, transfers
and the inventory reports that aggregate them."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.integration.postgres.api import (
    Api,
    make_location,
    make_movement,
    make_product,
    make_warehouse,
)


@pytest.fixture
def api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def store(api):
    """A warehouse with two locations and one product (cost 6.00)."""
    warehouse = make_warehouse(api)
    return {
        "warehouse": warehouse,
        "shelf": make_location(api, warehouse["id"], "A1"),
        "backroom": make_location(api, warehouse["id"], "B1"),
        "product": make_product(api, minStock=8, reorderPoint=10),
    }


def _stock(api: Api, product_id: int, location_id: int) -> dict:
    [stock] = api.get(
        "/api/admin/stock", params={"productId": product_id, "locationId": location_id}
    )
    return stock


def test_movements_drive_stock_and_inventory_reports(api, store):
    product, shelf = store["product"], store["shelf"]
    ten_days_ago = datetime.now() - timedelta(days=10)
    make_movement(api, product["id"], 10, shelf["id"], date=ten_days_ago.isoformat())
    make_movement(api, product["id"], -4, shelf["id"])

    assert _stock(api, product["id"], shelf["id"])["quantity"] == 6

    rotation = api.get(
        "/api/admin/reports/inventory/rotation",
        params={"fromDate": str(date.today() - timedelta(days=30))},
    )
    assert [(r["totalIn"], r["totalOut"], r["currentStock"]) for r in rotation] == [
        (10, 4, 6)
    ]

    valuation = api.get("/api/admin/reports/inventory/valuation")
    assert valuation["items"][0]["quantity"] == 6
    assert valuation["totalValue"] == 36.0

    past = api.get(
        "/api/admin/reports/inventory/valuation",
        params={"asOfDate": str(date.today() - timedelta(days=5))},
    )
    assert past["items"][0]["quantity"] == 10
    assert past["totalValue"] == 60.0

    history = api.get(
        "/api/admin/reports/inventory/movements",
        params={"warehouseId": store["warehouse"]["id"]},
    )
    assert sorted(m["quantity"] for m in history) == [-4, 10]

    [summary] = api.get(
        "/api/admin/reports/inventory/summary",
        params={"warehouseId": store["warehouse"]["id"]},
    )
    assert summary["totalQuantity"] == 6
    assert summary["totalValue"] == 36.0


def test_out_movement_beyond_stock_is_rejected(api, store):
    product, shelf = store["product"], store["shelf"]
    make_movement(api, product["id"], 2, shelf["id"])

    api.error(
        "POST",
        "/api/admin/movements",
        400,
        json={
            "productId": product["id"],
            "quantity": -3,
            "type": "OUT",
            "locationId": shelf["id"],
        },
    )

    assert _stock(api, product["id"], shelf["id"])["quantity"] == 2


def test_out_movement_without_stock_is_rejected_not_stored_negative(api, store):
    product, shelf, backroom = store["product"], store["shelf"], store["backroom"]
    make_movement(api, product["id"], 5, shelf["id"])

    for location_id in (backroom["id"], None):
        error = api.error(
            "POST",
            "/api/admin/movements",
            400,
            json={
                "productId": product["id"],
                "quantity": -1,
                "type": "OUT",
                "locationId": location_id,
            },
        )
        assert error["code"] == "INSUFFICIENT_STOCK"

    rows = api.get("/api/admin/stock", params={"productId": product["id"]})
    assert [(r["locationId"], r["quantity"]) for r in rows] == [(shelf["id"], 5)]


def test_out_movement_cannot_take_units_reserved_by_a_transfer(api, store):
    product, shelf, backroom = store["product"], store["shelf"], store["backroom"]
    make_movement(api, product["id"], 10, backroom["id"])
    transfer = api.post(
        "/api/admin/transfers",
        {"sourceLocationId": backroom["id"], "destinationLocationId": shelf["id"]},
    )
    api.post(
        f"/api/admin/transfers/{transfer['id']}/items",
        {"productId": product["id"], "quantity": 8},
    )
    api.post(f"/api/admin/transfers/{transfer['id']}/confirm")

    error = api.error(
        "POST",
        "/api/admin/movements",
        400,
        json={
            "productId": product["id"],
            "quantity": -3,
            "type": "OUT",
            "locationId": backroom["id"],
        },
    )
    make_movement(api, product["id"], -2, backroom["id"])

    assert error["code"] == "INSUFFICIENT_STOCK"
    source = _stock(api, product["id"], backroom["id"])
    assert (source["quantity"], source["reservedQuantity"]) == (8, 8)
    received = api.post(f"/api/admin/transfers/{transfer['id']}/receive")
    assert received["status"] == "received"


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        ("UPDATE stocks SET quantity = -1", "ck_stocks_quantity_non_negative"),
        (
            "UPDATE stocks SET reserved_quantity = quantity + 1",
            "ck_stocks_reserved_quantity_range",
        ),
        (
            "UPDATE stocks SET reserved_quantity = -1",
            "ck_stocks_reserved_quantity_range",
        ),
        (
            "INSERT INTO stocks (tenant_id, product_id, location_id, quantity,"
            " reserved_quantity) SELECT tenant_id, product_id, NULL, -4, 0 FROM stocks",
            "ck_stocks_quantity_non_negative",
        ),
    ],
)
def test_the_database_rejects_negative_or_over_reserved_stock(
    api, store, pg_engine, statement, constraint
):
    """The last barrier: a write that skips the domain (as the superuser,
    without row-level security) still can't leave a stock row below zero"""
    make_movement(api, store["product"]["id"], 3, store["shelf"]["id"])

    with pytest.raises(IntegrityError) as error, pg_engine.begin() as conn:
        conn.execute(text(statement))

    diag = getattr(error.value.orig, "diag", None)
    assert diag is not None
    assert diag.constraint_name == constraint


def test_a_manual_movement_has_no_document(api, store):
    """`referenceType`/`referenceId` belong to the documents that move stock
    (sales, refunds, adjustments...): the body can't claim one"""
    movement = make_movement(
        api,
        store["product"]["id"],
        5,
        store["shelf"]["id"],
        referenceType="sale",
        referenceId=1,
    )

    assert (movement["referenceType"], movement["referenceId"]) == (None, None)


def test_stock_alerts_follow_product_thresholds(api, store):
    product, shelf = store["product"], store["shelf"]
    make_movement(api, product["id"], 9, shelf["id"])
    warehouse_id = store["warehouse"]["id"]

    reorder = api.get(
        "/api/admin/alerts/reorder-point", params={"warehouseId": warehouse_id}
    )
    low = api.get("/api/admin/alerts/low-stock", params={"warehouseId": warehouse_id})

    assert [a["productId"] for a in reorder] == [product["id"]]
    assert low == []


def test_confirming_an_adjustment_moves_stock_to_the_counted_quantity(api, store):
    product, shelf = store["product"], store["shelf"]
    make_movement(api, product["id"], 10, shelf["id"])
    adjustment = api.post(
        "/api/admin/adjustments",
        {"warehouseId": store["warehouse"]["id"], "reason": "physical_count"},
    )
    item = api.post(
        f"/api/admin/adjustments/{adjustment['id']}/items",
        {"productId": product["id"], "locationId": shelf["id"], "actualQuantity": 7},
    )
    assert item["expectedQuantity"] == 10

    confirmed = api.post(f"/api/admin/adjustments/{adjustment['id']}/confirm")

    assert confirmed["status"] == "confirmed"
    assert _stock(api, product["id"], shelf["id"])["quantity"] == 7
    error = api.error(
        "PUT",
        f"/api/admin/adjustment-items/{item['id']}",
        400,
        json={"actualQuantity": 1},
    )
    assert error["code"] == "INVALID_ADJUSTMENT_STATUS"


def test_transfer_reserves_on_confirm_and_moves_stock_on_receive(api, store):
    product, shelf, backroom = store["product"], store["shelf"], store["backroom"]
    make_movement(api, product["id"], 10, backroom["id"])
    transfer = api.post(
        "/api/admin/transfers",
        {"sourceLocationId": backroom["id"], "destinationLocationId": shelf["id"]},
    )
    api.post(
        f"/api/admin/transfers/{transfer['id']}/items",
        {"productId": product["id"], "quantity": 4},
    )

    api.post(f"/api/admin/transfers/{transfer['id']}/confirm")
    assert _stock(api, product["id"], backroom["id"])["reservedQuantity"] == 4

    received = api.post(f"/api/admin/transfers/{transfer['id']}/receive")

    assert received["status"] == "received"
    source = _stock(api, product["id"], backroom["id"])
    assert (source["quantity"], source["reservedQuantity"]) == (6, 0)
    assert _stock(api, product["id"], shelf["id"])["quantity"] == 4


def test_cancelling_a_confirmed_transfer_releases_the_reservation(api, store):
    product, shelf, backroom = store["product"], store["shelf"], store["backroom"]
    make_movement(api, product["id"], 5, backroom["id"])
    transfer = api.post(
        "/api/admin/transfers",
        {"sourceLocationId": backroom["id"], "destinationLocationId": shelf["id"]},
    )
    api.post(
        f"/api/admin/transfers/{transfer['id']}/items",
        {"productId": product["id"], "quantity": 5},
    )
    api.post(f"/api/admin/transfers/{transfer['id']}/confirm")

    cancelled = api.post(f"/api/admin/transfers/{transfer['id']}/cancel")

    assert cancelled["status"] == "cancelled"
    source = _stock(api, product["id"], backroom["id"])
    assert (source["quantity"], source["reservedQuantity"]) == (5, 0)


def test_transfer_without_enough_stock_cannot_be_confirmed(api, store):
    product, shelf, backroom = store["product"], store["shelf"], store["backroom"]
    make_movement(api, product["id"], 2, backroom["id"])
    transfer = api.post(
        "/api/admin/transfers",
        {"sourceLocationId": backroom["id"], "destinationLocationId": shelf["id"]},
    )
    api.post(
        f"/api/admin/transfers/{transfer['id']}/items",
        {"productId": product["id"], "quantity": 3},
    )

    error = api.error("POST", f"/api/admin/transfers/{transfer['id']}/confirm", 400)

    assert error["code"] == "INSUFFICIENT_STOCK"

    assert api.get(f"/api/admin/transfers/{transfer['id']}")["status"] == "draft"


def test_serial_status_transitions(api, store):
    serial = api.post(
        "/api/admin/serials",
        {"productId": store["product"]["id"], "serialNumber": "SN-9"},
    )
    path = f"/api/admin/serials/{serial['id']}/status"

    assert api.put(path, {"status": "reserved"})["status"] == "reserved"
    error = api.error("PUT", path, 400, json={"status": "available"})

    assert error["code"] == "INVALID_SERIAL_STATUS"
    assert api.get(f"/api/admin/serials/{serial['id']}")["status"] == "reserved"
