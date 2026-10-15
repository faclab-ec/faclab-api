"""Specifications translated to SQL (`to_query_criteria`) and run by PostgreSQL,
exercised through the endpoints that use them."""

from datetime import date, timedelta

import pytest

from src.auth.domain.entities import Role
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


def test_product_search_matches_sku_barcode_or_name(api, client, auth_headers):
    make_product(api, "SKU-COF", name="Café molido", barcode="7861234500011")
    make_product(api, "SKU-TEA", name="Té verde")
    pos = Api(client, auth_headers(Role.CASHIER))

    def search(term: str) -> list[str]:
        found = pos.get("/api/pos/products/search", params={"term": term})
        return sorted(p["sku"] for p in found)

    assert search("SKU-TEA") == ["SKU-TEA"]
    assert search("7861234500011") == ["SKU-COF"]
    assert search("CAFÉ") == ["SKU-COF"]
    assert search("nothing") == []


def test_products_filtered_by_category(api):
    drinks = api.post("/api/admin/categories", {"name": "Bebidas"})
    make_product(api, "SKU-1", categoryId=drinks["id"])
    make_product(api, "SKU-2")

    products = api.get("/api/admin/products", params={"categoryId": drinks["id"]})

    assert [p["sku"] for p in products] == ["SKU-1"]


def test_lots_filtered_by_product_and_expiry(api):
    product = make_product(api, "SKU-1")
    other = make_product(api, "SKU-2")
    today = date.today()

    def lot(product_id: int, number: str, expires_in: int | None) -> dict:
        expiration = None if expires_in is None else str(today + timedelta(expires_in))
        return api.post(
            "/api/admin/lots",
            {
                "productId": product_id,
                "lotNumber": number,
                "initialQuantity": 5,
                "expirationDate": expiration,
            },
        )

    soon = lot(product["id"], "SOON", 10)
    lot(product["id"], "LATER", 90)
    lot(product["id"], "NEVER", None)
    used_up = lot(product["id"], "EMPTY", 5)
    api.put(f"/api/admin/lots/{used_up['id']}", {"currentQuantity": 0})
    other_soon = lot(other["id"], "OTHER", 3)

    by_product = api.get("/api/admin/lots", params={"productId": product["id"]})
    expiring = api.get("/api/admin/alerts/expiring-lots", params={"days": 30})

    assert len(by_product) == 4
    assert sorted(a["lotId"] for a in expiring) == [soon["id"], other_soon["id"]]


def test_stock_alerts_respect_warehouse(api):
    main = make_warehouse(api, "MAIN")
    other = make_warehouse(api, "OTHER")
    product = make_product(api, minStock=5, reorderPoint=5)
    make_movement(api, product["id"], 3, make_location(api, main["id"])["id"])
    make_movement(api, product["id"], 50, make_location(api, other["id"], "B1")["id"])

    def low(warehouse_id: int) -> list[int]:
        alerts = api.get(
            "/api/admin/alerts/low-stock", params={"warehouseId": warehouse_id}
        )
        return [a["productId"] for a in alerts]

    assert low(main["id"]) == [product["id"]]
    assert low(other["id"]) == []


def test_adjustments_and_transfers_filtered_by_status(api):
    warehouse = make_warehouse(api)
    source = make_location(api, warehouse["id"], "A1")
    destination = make_location(api, warehouse["id"], "A2")
    kept = api.post(
        "/api/admin/adjustments",
        {"warehouseId": warehouse["id"], "reason": "damaged"},
    )
    cancelled = api.post(
        "/api/admin/adjustments",
        {"warehouseId": warehouse["id"], "reason": "theft"},
    )
    api.post(f"/api/admin/adjustments/{cancelled['id']}/cancel")
    api.post(
        "/api/admin/transfers",
        {"sourceLocationId": source["id"], "destinationLocationId": destination["id"]},
    )

    drafts = api.get(
        "/api/admin/adjustments",
        params={"status": "draft", "warehouseId": warehouse["id"]},
    )
    transfers = api.get(
        "/api/admin/transfers",
        params={"status": "draft", "sourceLocationId": source["id"]},
    )

    assert [a["id"] for a in drafts] == [kept["id"]]
    assert len(transfers) == 1


def test_parked_sales(api, client, auth_headers):
    pos = Api(client, auth_headers(Role.CASHIER))
    pos.post("/api/pos/shifts/open", {"openingBalance": "0"})
    parked = pos.post("/api/pos/sales", {"isFinalConsumer": True})
    pos.post("/api/pos/sales", {"isFinalConsumer": True})
    pos.post(f"/api/pos/sales/{parked['id']}/park")

    assert [s["id"] for s in pos.get("/api/pos/sales/parked")] == [parked["id"]]
