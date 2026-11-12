"""Supplier returns against PostgreSQL (S5.7): goods of a received order go
back to the supplier, leave the stock at the location's average cost and lower
what is owed to the supplier; what was already paid is left to refund."""

from datetime import datetime

import pytest
from sqlalchemy import select

from src.inventory.movement.infra.models import MovementModel
from tests.integration.postgres.api import (
    Api,
    concurrently,
    make_location,
    make_movement,
    make_product,
    make_warehouse,
    national_id,
)


@pytest.fixture
def api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def received(api):
    """10 units at 6.00 with 15 % VAT received at a location: 69.00 owed to a
    supplier with 30 days of credit"""
    supplier = api.post(
        "/api/admin/suppliers",
        {
            "name": "Distribuidora Andina",
            "taxId": national_id(4) + "001",
            "taxType": 1,
            "paymentTerms": 30,
        },
    )
    product = make_product(api, taxCode="VAT_15")
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
    api.post(f"/api/admin/purchase-orders/{po['id']}/send")
    api.post(
        f"/api/admin/purchase-orders/{po['id']}/receive",
        {
            "items": [
                {
                    "purchaseOrderItemId": item["id"],
                    "quantityReceived": 10,
                    "locationId": location["id"],
                }
            ],
            "supplierInvoiceNumber": "001-001-000000777",
        },
    )
    return {
        "supplier": supplier,
        "product": product,
        "location": location,
        "po": po,
        "item": item,
    }


def _draft(api: Api, received: dict, quantity: float) -> dict:
    supplier_return = api.post(
        "/api/admin/supplier-returns", {"purchaseOrderId": received["po"]["id"]}
    )
    api.post(
        f"/api/admin/supplier-returns/{supplier_return['id']}/items",
        {
            "purchaseOrderItemId": received["item"]["id"],
            "quantity": quantity,
            "locationId": received["location"]["id"],
        },
    )
    return supplier_return


def _stock(api: Api, product_id: int) -> float:
    rows = api.get("/api/admin/stock", params={"productId": product_id})
    return sum(row["quantity"] for row in rows)


def _owed(api: Api, supplier_id: int) -> float:
    return api.get(f"/api/admin/supplier-accounts/{supplier_id}")["outstanding"]


def test_a_confirmed_return_lowers_the_stock_and_what_is_owed(
    api, received, db_session
):
    """Acceptance (S5.7): 4 of the 10 go back; 6 stay in stock and the 69.00
    owed goes down by 27.60 (24.00 + 3.60 of VAT)"""
    supplier_id = received["supplier"]["id"]
    assert _owed(api, supplier_id) == 69.0
    draft = _draft(api, received, 4)
    year = datetime.now().year
    assert draft["number"] == f"DP-{year}-0001"
    assert draft["status"] == "draft"

    confirmed = api.post(
        f"/api/admin/supplier-returns/{draft['id']}/confirm",
        {"supplierCreditNoteNumber": "001-001-000000045"},
    )

    assert confirmed["status"] == "confirmed"
    assert (confirmed["subtotal"], confirmed["tax"], confirmed["total"]) == (
        24.0,
        3.6,
        27.6,
    )
    assert (confirmed["creditedAmount"], confirmed["refundDue"]) == (27.6, 0.0)
    assert confirmed["supplierCreditNoteNumber"] == "001-001-000000045"
    assert _stock(api, received["product"]["id"]) == 6
    assert _owed(api, supplier_id) == 41.4

    # It left at the location's average cost, referenced to the return
    [movement] = db_session.scalars(
        select(MovementModel).where(MovementModel.reference_type == "supplier_return")
    ).all()
    assert (movement.quantity, movement.unit_cost, movement.reference_id) == (
        -4,
        6,
        draft["id"],
    )
    [item] = api.get(f"/api/admin/purchase-orders/{received['po']['id']}/items")
    assert item["quantityReturned"] == 4
    [payable] = api.get("/api/admin/payables", params={"supplierId": supplier_id})
    detail = api.get(f"/api/admin/payables/{payable['id']}")
    assert [
        (a["kind"], a["amount"], a["documentNumber"]) for a in detail["applications"]
    ] == [("RETURN", 27.6, draft["number"])]


def test_a_return_to_a_supplier_already_paid_is_left_to_refund(api, received):
    supplier_id = received["supplier"]["id"]
    api.post(
        "/api/admin/supplier-payments",
        {"supplierId": supplier_id, "amount": "69.00", "paymentMethod": "TRANSFER"},
    )
    draft = _draft(api, received, 2)

    confirmed = api.post(f"/api/admin/supplier-returns/{draft['id']}/confirm", {})

    assert (
        confirmed["total"],
        confirmed["creditedAmount"],
        confirmed["refundDue"],
    ) == (
        13.8,
        0.0,
        13.8,
    )
    account = api.get(f"/api/admin/supplier-accounts/{supplier_id}")
    assert account["outstanding"] == 0
    assert [(r["number"], r["refundDue"]) for r in account["returns"]] == [
        (draft["number"], 13.8)
    ]


def test_a_return_takes_at_most_what_was_received_and_not_returned(api, received):
    draft = api.post(
        "/api/admin/supplier-returns", {"purchaseOrderId": received["po"]["id"]}
    )
    error = api.error(
        "POST",
        f"/api/admin/supplier-returns/{draft['id']}/items",
        400,
        json={"purchaseOrderItemId": received["item"]["id"], "quantity": 11},
    )
    assert error["code"] == "EXCEEDS_RETURNABLE_QUANTITY"

    # Two drafts of 6 fit one by one; the second can't be confirmed after the first
    first, second = _draft(api, received, 6), _draft(api, received, 6)
    api.post(f"/api/admin/supplier-returns/{first['id']}/confirm", {})
    error = api.error(
        "POST", f"/api/admin/supplier-returns/{second['id']}/confirm", 400, json={}
    )
    assert error["code"] == "EXCEEDS_RETURNABLE_QUANTITY"
    assert _stock(api, received["product"]["id"]) == 4


def test_concurrent_confirms_of_one_order_line_take_turns(api, admin, received):
    """Two drafts of 6 of the same 10 confirmed at once: the order line is
    locked, so one goes through and the other finds only 4 left"""
    first, second = _draft(api, received, 6), _draft(api, received, 6)

    responses = concurrently(
        *(
            lambda client, id=draft["id"]: client.post(
                f"/api/admin/supplier-returns/{id}/confirm", json={}, headers=admin
            )
            for draft in (first, second)
        )
    )

    assert sorted(r.status_code for r in responses) == [200, 400]
    assert _stock(api, received["product"]["id"]) == 4


def test_goods_no_longer_in_stock_cant_go_back(api, received):
    make_movement(
        api, received["product"]["id"], -8, received["location"]["id"], reason="Venta"
    )
    draft = _draft(api, received, 4)

    error = api.error(
        "POST", f"/api/admin/supplier-returns/{draft['id']}/confirm", 400, json={}
    )

    assert error["code"] == "INSUFFICIENT_STOCK"
    assert api.get(f"/api/admin/supplier-returns/{draft['id']}")["status"] == "draft"
    assert _owed(api, received["supplier"]["id"]) == 69.0


def test_an_order_with_nothing_received_has_no_return(api, received):
    po = api.post(
        "/api/admin/purchase-orders", {"supplierId": received["supplier"]["id"]}
    )

    error = api.error(
        "POST", "/api/admin/supplier-returns", 400, json={"purchaseOrderId": po["id"]}
    )

    assert error["code"] == "PURCHASE_ORDER_NOT_RETURNABLE"


def test_a_draft_is_edited_and_deleted(api, received):
    draft = _draft(api, received, 2)
    [line] = api.get(f"/api/admin/supplier-returns/{draft['id']}/items")
    assert (line["productName"], line["subtotal"], line["taxAmount"]) == (
        received["product"]["name"],
        12.0,
        1.8,
    )

    api.put(f"/api/admin/supplier-return-items/{line['id']}", {"quantity": 3})
    assert api.get(f"/api/admin/supplier-returns/{draft['id']}")["total"] == 20.7
    api.delete(f"/api/admin/supplier-returns/{draft['id']}")

    assert api.get("/api/admin/supplier-returns") == []
