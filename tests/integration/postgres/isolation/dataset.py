"""One tenant's full graph, built through the API: the isolation suite builds it
for tenant A and tenant B and calls every route of one with the ids of the other.

Every name, SKU and code carries the tenant's marker, and tax ids come from its
seed, so a response of A that shows any of B's markers is a leak."""

from datetime import date, timedelta
from typing import Any

from tests.integration.postgres.api import (
    Api,
    make_customer,
    make_location,
    make_movement,
    make_product,
    make_supplier,
    make_warehouse,
    national_id,
)

# An id no sequence reaches: what a row of another tenant must look like
MISSING = 2_000_000_000
MISSING_TEXT = "NO-SUCH-VALUE"

Ids = dict[str, Any]


def customer_tax_id(seed: int) -> str:
    return national_id(seed * 10 + 1)


def supplier_tax_id(seed: int) -> str:
    return national_id(seed * 10 + 2) + "001"


def build_tenant(api: Api, marker: str, seed: int) -> Ids:
    """Every kind of row a route can reach, with the state its routes need: a
    draft and a partly received order, a draft adjustment and transfer, an open
    shift with a draft and a confirmed sale and a pending refund"""
    m = marker
    ids: Ids = {"marker": m, "seed": seed}

    ids["category"] = api.post("/api/admin/categories", {"name": f"{m} Herramientas"})[
        "id"
    ]
    ids["uom"] = api.post(
        "/api/admin/units-of-measure", {"name": f"{m} Unidad", "symbol": f"{m}-u"}
    )["id"]
    ids["sku"] = f"{m}-SKU-1"
    # Thresholds above its stock: the low stock and reorder alerts list it
    ids["product"] = make_product(
        api,
        ids["sku"],
        name=f"{m} Martillo",
        barcode=f"{seed}786100000001",
        categoryId=ids["category"],
        unitOfMeasureId=ids["uom"],
        minStock=100,
        reorderPoint=100,
    )["id"]
    ids["product_out"] = make_product(api, f"{m}-SKU-2", name=f"{m} Clavo")["id"]

    ids["warehouse"] = make_warehouse(api, f"{m}-WH1")["id"]
    ids["location"] = make_location(api, ids["warehouse"], f"{m}-A1")["id"]
    ids["location2"] = make_location(api, ids["warehouse"], f"{m}-A2")["id"]
    make_movement(api, ids["product"], 50, ids["location"])
    # Out of stock: a stock row at zero
    make_movement(api, ids["product_out"], 5, ids["location"])
    make_movement(api, ids["product_out"], -5, ids["location"])

    ids["lot"] = api.post(
        "/api/admin/lots",
        {
            "productId": ids["product"],
            "lotNumber": f"{m}-LOT-1",
            "initialQuantity": 5,
            "expirationDate": (date.today() + timedelta(days=10)).isoformat(),
        },
    )["id"]
    ids["serial"] = api.post(
        "/api/admin/serials",
        {
            "productId": ids["product"],
            "serialNumber": f"{m}-SN-1",
            "lotId": ids["lot"],
            "locationId": ids["location"],
        },
    )["id"]

    ids["tax_id"] = customer_tax_id(seed)
    ids["customer"] = make_customer(api, seed * 10 + 1, name=f"{m} Cliente")["id"]
    ids["customer_contact"] = api.post(
        f"/api/admin/customers/{ids['customer']}/contacts", {"name": f"{m} Contacto"}
    )["id"]
    ids["supplier"] = make_supplier(api, seed * 10 + 2, name=f"{m} Proveedor")["id"]
    ids["supplier_contact"] = api.post(
        f"/api/admin/suppliers/{ids['supplier']}/contacts", {"name": f"{m} Vendedor"}
    )["id"]
    ids["supplier_product"] = api.post(
        f"/api/admin/suppliers/{ids['supplier']}/products",
        {
            "productId": ids["product"],
            "purchasePrice": "5.00",
            "supplierSku": f"{m}-SUP-1",
        },
    )["id"]

    ids["po_draft"], ids["po_draft_item"] = _order(api, ids)
    ids["po_sent"], ids["po_sent_item"] = _order(api, ids)
    api.post(f"/api/admin/purchase-orders/{ids['po_sent']}/send")
    # Partly received: it has a receipt and can still receive
    api.post(
        f"/api/admin/purchase-orders/{ids['po_sent']}/receive",
        {
            "items": [
                {
                    "purchaseOrderItemId": ids["po_sent_item"],
                    "quantityReceived": 1,
                    "locationId": ids["location"],
                }
            ]
        },
    )

    ids["adjustment"] = api.post(
        "/api/admin/adjustments",
        {"warehouseId": ids["warehouse"], "reason": "physical_count"},
    )["id"]
    ids["adjustment_item"] = api.post(
        f"/api/admin/adjustments/{ids['adjustment']}/items",
        {
            "productId": ids["product"],
            "locationId": ids["location"],
            "actualQuantity": 49,
        },
    )["id"]
    ids["transfer"] = api.post(
        "/api/admin/transfers",
        {
            "sourceLocationId": ids["location"],
            "destinationLocationId": ids["location2"],
        },
    )["id"]
    ids["transfer_item"] = api.post(
        f"/api/admin/transfers/{ids['transfer']}/items",
        {"productId": ids["product"], "quantity": 1},
    )["id"]

    ids["user"] = api.post(
        "/api/admin/users",
        {
            "username": f"{m.lower()}-viewer",
            "email": f"{m.lower()}-viewer@test.local",
            "password": "Viewer-Pass-2026!",
            "fullName": f"{m} Viewer",
            "role": 4,
        },
    )["id"]

    ids["shift"] = api.post("/api/pos/shifts/open", {"openingBalance": "100.00"})["id"]
    ids["cash_movement"] = api.post(
        f"/api/pos/shifts/{ids['shift']}/cash-movements",
        {"type": "IN", "amount": "10.00", "reason": f"{m} fondo"},
    )["id"]
    ids["pos_draft"] = api.post("/api/pos/sales", {"customerId": ids["customer"]})["id"]
    api.post(
        f"/api/pos/sales/{ids['pos_draft']}/items",
        {"productId": ids["product"], "quantity": 1, "unitPrice": "10.00"},
    )
    [item] = api.get(f"/api/pos/sales/{ids['pos_draft']}/items")
    ids["pos_draft_item"] = item["id"]
    # 2 x 10.00 + VAT 15 %
    ids["sale"] = api.post(
        "/api/pos/sales/quick",
        {
            "customerId": ids["customer"],
            "items": [{"productId": ids["product"], "quantity": 2}],
            "payments": [{"amount": "23.00", "paymentMethod": "CASH"}],
        },
    )["id"]
    [item] = api.get(f"/api/pos/sales/{ids['sale']}/items")
    ids["sale_item"] = item["id"]
    ids["refund"] = api.post(
        "/api/pos/refunds",
        {
            "originalSaleId": ids["sale"],
            "items": [{"saleItemId": ids["sale_item"], "quantity": 1}],
            "reason": f"{m} devolución",
        },
    )["id"]
    return ids


def _order(api: Api, ids: Ids) -> tuple[int, int]:
    order = api.post("/api/admin/purchase-orders", {"supplierId": ids["supplier"]})
    item = api.post(
        "/api/admin/purchase-order-items",
        {
            "purchaseOrderId": order["id"],
            "productId": ids["product"],
            "quantityOrdered": 3,
            "unitCost": "5.00",
        },
    )
    return order["id"], item["id"]
