"""Purchasing flows against PostgreSQL: purchase orders, receipts and their
inventory effects (stock, lots, serial numbers)."""

import pytest
from sqlalchemy import select

from src.inventory.lot.infra.models import LotModel, MovementLotItemModel
from src.inventory.movement.infra.models import MovementModel
from tests.integration.postgres.api import (
    Api,
    make_location,
    make_product,
    make_supplier,
    make_warehouse,
)


@pytest.fixture
def api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def order(api):
    """A sent purchase order for 10 units at 6.00, plus where to receive them."""
    supplier = make_supplier(api)
    product = make_product(api)
    location = make_location(api, make_warehouse(api)["id"])
    po = api.post("/api/admin/purchase-orders", {"supplierId": supplier["id"]})
    item = api.post(
        "/api/admin/purchase-order-items",
        {
            "purchaseOrderId": po["id"],
            "productId": product["id"],
            "quantityOrdered": 10,
            "unitCost": "6.00",
        },
    )
    return {"po": po, "item": item, "product": product, "location": location}


def _receive(api: Api, po_id: int, item_id: int, quantity: int, **extra) -> dict:
    return api.post(
        f"/api/admin/purchase-orders/{po_id}/receive",
        {
            "items": [
                {"purchaseOrderItemId": item_id, "quantityReceived": quantity, **extra}
            ]
        },
    )


def _stock_quantity(api: Api, product_id: int) -> int:
    rows = api.get("/api/admin/stock", params={"productId": product_id})
    return sum(row["quantity"] for row in rows)


def test_draft_order_cannot_be_received(api, order):
    error = api.error(
        "POST",
        f"/api/admin/purchase-orders/{order['po']['id']}/receive",
        400,
        json={
            "items": [
                {"purchaseOrderItemId": order["item"]["id"], "quantityReceived": 1}
            ]
        },
    )

    assert "status" in error["message"]


def test_partial_then_full_receipt_with_lots(api, db_session, order):
    po_id, item_id = order["po"]["id"], order["item"]["id"]
    location_id, product_id = order["location"]["id"], order["product"]["id"]
    api.post(f"/api/admin/purchase-orders/{po_id}/send")

    _receive(api, po_id, item_id, 4, locationId=location_id, lotNumber="L-1")
    assert api.get(f"/api/admin/purchase-orders/{po_id}")["status"] == "partial"
    assert _stock_quantity(api, product_id) == 4

    _receive(api, po_id, item_id, 6, locationId=location_id, lotNumber="L-2")
    assert api.get(f"/api/admin/purchase-orders/{po_id}")["status"] == "received"
    assert _stock_quantity(api, product_id) == 10

    # Each lot is linked to the IN movement of its own receipt
    links = db_session.execute(
        select(LotModel.lot_number, MovementModel.quantity)
        .join(MovementLotItemModel, MovementLotItemModel.lot_id == LotModel.id)
        .join(MovementModel, MovementModel.id == MovementLotItemModel.movement_id)
        .order_by(LotModel.lot_number)
    ).all()
    assert [tuple(row) for row in links] == [("L-1", 4), ("L-2", 6)]

    api.error(
        "POST",
        f"/api/admin/purchase-orders/{po_id}/receive",
        400,
        json={"items": [{"purchaseOrderItemId": item_id, "quantityReceived": 1}]},
    )


def test_repeated_lines_cannot_over_receive(api, order):
    po_id, item_id = order["po"]["id"], order["item"]["id"]
    api.post(f"/api/admin/purchase-orders/{po_id}/send")

    api.error(
        "POST",
        f"/api/admin/purchase-orders/{po_id}/receive",
        400,
        json={
            "items": [
                {"purchaseOrderItemId": item_id, "quantityReceived": 6},
                {"purchaseOrderItemId": item_id, "quantityReceived": 6},
            ]
        },
    )

    assert _stock_quantity(api, order["product"]["id"]) == 0


def test_receipt_registers_serial_numbers(api, order):
    po_id, item_id = order["po"]["id"], order["item"]["id"]
    api.post(f"/api/admin/purchase-orders/{po_id}/send")

    _receive(
        api,
        po_id,
        item_id,
        2,
        locationId=order["location"]["id"],
        serialNumbers=["SN-1", "SN-2"],
    )

    serials = api.get(
        "/api/admin/serials", params={"productId": order["product"]["id"]}
    )
    assert sorted(s["serialNumber"] for s in serials) == ["SN-1", "SN-2"]
    assert {s["status"] for s in serials} == {"available"}


def test_deleting_an_older_draft_does_not_reuse_a_live_order_number(api, order):
    supplier_id = order["po"]["supplierId"]
    older = api.post("/api/admin/purchase-orders", {"supplierId": supplier_id})
    latest = api.post("/api/admin/purchase-orders", {"supplierId": supplier_id})
    api.delete(f"/api/admin/purchase-orders/{older['id']}")

    newer = api.post("/api/admin/purchase-orders", {"supplierId": supplier_id})

    assert latest["orderNumber"].endswith("-0003")
    assert newer["orderNumber"].endswith("-0004")
