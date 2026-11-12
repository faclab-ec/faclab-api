"""Weighted average cost and the valued kardex against PostgreSQL (S5.6).

Two purchases at different prices give their weighted average; exits leave at
it, a transfer carries it to another warehouse, a sale and its cancellation go
out and back at it, and the kardex of each warehouse adds up to its valuation.
"""

from datetime import date

import pytest

from src.auth.domain.entities import Role
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    make_location,
    make_movement,
    make_product,
    make_supplier,
    make_terminal,
    make_warehouse,
)

TODAY = str(date.today())


@pytest.fixture
def api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def store(api):
    """Two warehouses with a location each, a product (purchase price 6.00) and
    its supplier"""
    main = make_warehouse(api, "WH-M")
    north = make_warehouse(api, "WH-N")
    return {
        "supplier": make_supplier(api),
        "main": main,
        "north": north,
        "shelf": make_location(api, main["id"], "A1"),
        "north_shelf": make_location(api, north["id"], "N1"),
        "product": make_product(api, sku="CEM-50"),
    }


def _purchase(api: Api, store: dict, location_id: int, lines: list) -> None:
    """A purchase order of the store's product with one line per (quantity,
    unit cost[, extra fields]), received whole into the location, line by line"""
    product_id = store["product"]["id"]
    po = api.post("/api/admin/purchase-orders", {"supplierId": store["supplier"]["id"]})
    items = [
        api.post(
            "/api/admin/purchase-order-items",
            {
                "purchaseOrderId": po["id"],
                "productId": product_id,
                "quantityOrdered": quantity,
                "unitCost": cost,
                **extra,
            },
        )
        for quantity, cost, *rest in lines
        for extra in [rest[0] if rest else {}]
    ]
    api.post(f"/api/admin/purchase-orders/{po['id']}/send")
    for item, (quantity, *_) in zip(items, lines, strict=True):
        api.post(
            f"/api/admin/purchase-orders/{po['id']}/receive",
            {
                "items": [
                    {
                        "purchaseOrderItemId": item["id"],
                        "quantityReceived": quantity,
                        "locationId": location_id,
                    }
                ]
            },
        )


def _stock(api: Api, product_id: int, location_id: int) -> dict:
    [row] = api.get(
        "/api/admin/stock", params={"productId": product_id, "locationId": location_id}
    )
    return row


def _kardex(api: Api, product_id: int, warehouse_id: int) -> dict:
    return api.get(
        "/api/admin/reports/inventory/kardex",
        params={
            "productId": product_id,
            "warehouseId": warehouse_id,
            "fromDate": TODAY,
            "toDate": TODAY,
        },
    )


def _valued(api: Api, product_id: int, warehouse_id: int) -> tuple[float, float]:
    valuation = api.get(
        "/api/admin/reports/inventory/valuation", params={"warehouseId": warehouse_id}
    )
    [item] = [i for i in valuation["items"] if i["productId"] == product_id]
    return item["quantity"], item["totalValue"]


def _adds_up(kardex: dict) -> None:
    """Closing = opening + entries − exits, in quantity and in value"""
    opening, closing = kardex["opening"], kardex["closing"]
    entries, exits = kardex["totalIn"], kardex["totalOut"]
    assert closing["quantity"] == (
        opening["quantity"] + entries["quantity"] - exits["quantity"]
    )
    assert closing["value"] == pytest.approx(
        opening["value"] + entries["value"] - exits["value"], abs=1e-6
    )


def test_two_purchases_exits_and_a_transfer_keep_the_kardex_and_valuation_even(
    api, store
):
    product, shelf, north_shelf = store["product"], store["shelf"], store["north_shelf"]
    pid = product["id"]

    # 10 at 5.00 and 30 at 7.00: (50.00 + 210.00) / 40
    _purchase(api, store, shelf["id"], [(10, "5.00"), (30, "7.00")])
    stock = _stock(api, pid, shelf["id"])
    assert (stock["quantity"], stock["averageCost"]) == (40, 6.5)

    # An exit leaves at the average and doesn't change it
    out = make_movement(api, pid, -15, shelf["id"])
    assert out["unitCost"] == 6.5
    assert _stock(api, pid, shelf["id"])["averageCost"] == 6.5

    # A manual exit can't name its own cost
    error = api.error(
        "POST",
        "/api/admin/movements",
        400,
        json={
            "productId": pid,
            "quantity": -1,
            "type": "OUT",
            "locationId": shelf["id"],
            "unitCost": "1.00",
        },
    )
    assert error["code"] == "INVALID_MOVEMENT_TYPE"

    # 5 go to the north warehouse at the source's cost
    transfer = api.post(
        "/api/admin/transfers",
        {"sourceLocationId": shelf["id"], "destinationLocationId": north_shelf["id"]},
    )
    api.post(
        f"/api/admin/transfers/{transfer['id']}/items",
        {"productId": pid, "quantity": 5},
    )
    api.post(f"/api/admin/transfers/{transfer['id']}/confirm")
    api.post(f"/api/admin/transfers/{transfer['id']}/receive")
    north = _stock(api, pid, north_shelf["id"])
    assert (north["quantity"], north["averageCost"]) == (5, 6.5)

    main_kardex = _kardex(api, pid, store["main"]["id"])
    assert [
        (e["type"], e["inQuantity"], e["outQuantity"], e["unitCost"])
        for e in main_kardex["entries"]
    ] == [
        ("IN", 10, 0, 5.0),
        ("IN", 30, 0, 7.0),
        ("OUT", 0, 15, 6.5),
        ("OUT", 0, 5, 6.5),
    ]
    assert main_kardex["entries"][-1]["referenceType"] == "transfer"
    assert main_kardex["totalIn"] == {"quantity": 40, "value": 260.0}
    assert main_kardex["totalOut"] == {"quantity": 20, "value": 130.0}
    assert main_kardex["closing"] == {
        "quantity": 20,
        "value": 130.0,
        "averageCost": 6.5,
    }
    _adds_up(main_kardex)
    assert _valued(api, pid, store["main"]["id"]) == (20, 130.0)

    north_kardex = _kardex(api, pid, store["north"]["id"])
    assert north_kardex["closing"] == {"quantity": 5, "value": 32.5, "averageCost": 6.5}
    _adds_up(north_kardex)
    assert _valued(api, pid, store["north"]["id"]) == (5, 32.5)

    summary = api.get(
        "/api/admin/reports/inventory/summary",
        params={"warehouseId": store["main"]["id"]},
    )
    assert summary[0]["totalValue"] == 130.0


def test_a_box_costs_each_base_unit_its_share(api, store):
    product, shelf = store["product"], store["shelf"]
    box = api.post(
        f"/api/admin/products/{product['id']}/presentations",
        {"name": "Caja x12", "factor": 12},
    )

    _purchase(
        api,
        store,
        shelf["id"],
        [(2, "30.00", {"presentationId": box["id"]})],
    )

    stock = _stock(api, product["id"], shelf["id"])
    assert (stock["quantity"], stock["averageCost"]) == (24, 2.5)


def test_an_initial_balance_enters_at_the_cost_of_the_count(api, store):
    product, shelf = store["product"], store["shelf"]
    adjustment = api.post(
        "/api/admin/adjustments",
        {"warehouseId": store["main"]["id"], "reason": "physical_count"},
    )
    item = api.post(
        f"/api/admin/adjustments/{adjustment['id']}/items",
        {
            "productId": product["id"],
            "locationId": shelf["id"],
            "actualQuantity": 12,
            "unitCost": "4.25",
        },
    )
    assert item["unitCost"] == 4.25

    api.post(f"/api/admin/adjustments/{adjustment['id']}/confirm")

    stock = _stock(api, product["id"], shelf["id"])
    assert (stock["quantity"], stock["averageCost"]) == (12, 4.25)
    # Without a cost, a location that never had it takes the purchase price
    make_movement(api, product["id"], 3, store["north_shelf"]["id"])
    north = _stock(api, product["id"], store["north_shelf"]["id"])
    assert north["averageCost"] == 6.0


@pytest.fixture
def cashier_api(client, auth_headers, api, store) -> Api:
    terminal = make_terminal(api, store["shelf"]["id"])
    cashier = Api(client, at_terminal(auth_headers(Role.CASHIER), terminal))
    cashier.post("/api/pos/shifts/open", {"openingBalance": "0"})
    return cashier


def test_a_sale_leaves_at_the_average_and_its_cancellation_puts_it_back_at_it(
    api, store, cashier_api
):
    product, shelf = store["product"], store["shelf"]
    pid = product["id"]
    _purchase(api, store, shelf["id"], [(10, "5.00")])

    sale = cashier_api.post(
        "/api/pos/sales/quick",
        {
            "items": [{"productId": pid, "quantity": 4}],
            "payments": [{"amount": "46.00", "paymentMethod": "CASH"}],
        },
    )
    # Meanwhile 10 more at 8.00: the average is (6 × 5.00 + 10 × 8.00) / 16
    _purchase(api, store, shelf["id"], [(10, "8.00")])
    assert _stock(api, pid, shelf["id"])["averageCost"] == 6.875

    cashier_api.post(f"/api/pos/sales/{sale['id']}/cancel")

    # The 4 come back at the 5.00 they left at: (16 × 6.875 + 4 × 5.00) / 20
    stock = _stock(api, pid, shelf["id"])
    assert (stock["quantity"], stock["averageCost"]) == (20, 6.5)
    kardex = _kardex(api, pid, store["main"]["id"])
    sale_rows = [
        (e["type"], e["unitCost"])
        for e in kardex["entries"]
        if e["referenceType"] == "sale"
    ]
    assert sale_rows == [("OUT", 5.0), ("IN", 5.0)]
    assert kardex["closing"]["value"] == pytest.approx(130.0)
    _adds_up(kardex)
