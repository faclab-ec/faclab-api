"""Every route of `main.app` and how the isolation suite calls it.

A route is checked by what it takes:

- `path`: the dataset keys its path ids come from. Called by tenant A with B's
  ids, it must answer exactly as with ids that don't exist (`MISSING`); a GET
  must also answer B with its own data.
- `refs`: keys of the path, body, query or headers that point to another row.
  Each one,
  swapped for B's, must look missing too, and the call with A's own row must
  succeed (or, for a GET, answer something else), so the swap is what fails.
- A GET without path ids is a listing: after B exists it answers A exactly as
  before. One that can't run without its query (`needs_query`, a search) is
  checked through its refs only.
- A POST without path ids or refs creates a row of A that B can't see
  (`created`: the GET B would read it with).
- `exempt`: why the suite doesn't call it.

A new route without an entry fails `test_every_route_is_covered`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tests.integration.postgres.isolation.dataset import (
    Ids,
    customer_tax_id,
    supplier_tax_id,
)

Body = Callable[[Ids], dict[str, Any]]


@dataclass(frozen=True)
class Route:
    path: tuple[str, ...] = ()
    body: Body | None = None
    query: Body | None = None
    headers: Body | None = None
    refs: tuple[str, ...] = ()
    needs_query: bool = False
    created: str | None = None
    exempt: str | None = None


def _name(suffix: str) -> Body:
    return lambda ids: {"name": f"{ids['marker']} {suffix}"}


def _product(sku: str) -> Body:
    # The dataset's prices and thresholds: a PUT replaces every field, and the
    # alerts and reports read them
    return lambda ids: {
        "name": f"{ids['marker']} Producto",
        "sku": f"{ids['marker']}-{sku}",
        "categoryId": ids["category"],
        "unitOfMeasureId": ids["uom"],
        "purchasePrice": "6.00",
        "salePrice": "10.00",
        "minStock": 100,
        "reorderPoint": 100,
    }


def _location(code: str) -> Body:
    return lambda ids: {
        "warehouseId": ids["warehouse"],
        "name": f"{ids['marker']} Ubicación",
        "code": f"{ids['marker']}-{code}",
    }


def _receive(ids: Ids) -> dict:
    return {
        "items": [
            {
                "purchaseOrderItemId": ids["po_sent_item"],
                "quantityReceived": 1,
                "locationId": ids["location"],
            }
        ]
    }


def _warehouse(ids: Ids) -> dict:
    return {"warehouseId": ids["warehouse"]}


def _branch(ids: Ids) -> dict:
    return {"branchId": ids["branch"]}


def _terminal(code: str) -> Body:
    return lambda ids: {
        "emissionPointId": ids["emission_point"],
        "defaultLocationId": ids["location"],
        "code": f"{ids['marker']}-{code}",
        "name": f"{ids['marker']} Caja",
    }


def _payment(amount: str) -> Body:
    return lambda ids: {"amount": amount, "paymentMethod": "CASH"}


def _at_terminal(terminal: str = "terminal") -> Body:
    """The POS headers of an operation that starts at a terminal"""
    return lambda ids: {
        "X-Branch-Id": str(ids["branch"]),
        "X-Terminal-Id": str(ids[terminal]),
    }


def _in_branch(ids: Ids) -> dict:
    """The POS header of an operation on a sale, shift or refund of the branch"""
    return {"X-Branch-Id": str(ids["branch"])}


def _placement(ids: Ids) -> dict:
    """The branch and terminal filters of the POS histories and reports"""
    return {"branchId": ids["branch"], "terminalId": ids["terminal"]}


ADMIN = "/api/admin"
POS = "/api/pos"

ROUTES: dict[str, Route] = {
    # Organization
    f"POST {ADMIN}/branches": Route(
        body=lambda ids: {"establishmentCode": "009", "name": f"{ids['marker']} Sur"},
        created=f"{ADMIN}/branches/{{}}",
    ),
    f"GET {ADMIN}/branches": Route(),
    f"GET {ADMIN}/branches/{{id}}": Route(path=("branch",)),
    f"PUT {ADMIN}/branches/{{id}}": Route(
        path=("branch",),
        body=lambda ids: {"establishmentCode": "001", "name": f"{ids['marker']} M"},
    ),
    f"DELETE {ADMIN}/branches/{{id}}": Route(path=("branch",)),
    f"POST {ADMIN}/emission-points": Route(
        body=lambda ids: {"branchId": ids["branch"], "code": "002"}, refs=("branch",)
    ),
    f"GET {ADMIN}/emission-points": Route(query=_branch, refs=("branch",)),
    f"GET {ADMIN}/emission-points/{{id}}": Route(path=("emission_point",)),
    f"PUT {ADMIN}/emission-points/{{id}}": Route(
        path=("emission_point",), body=lambda ids: {"code": "001"}
    ),
    f"DELETE {ADMIN}/emission-points/{{id}}": Route(path=("emission_point",)),
    f"POST {ADMIN}/pos-terminals": Route(
        body=lambda ids: {"branchId": ids["branch"], **_terminal("CAJA-NEW")(ids)},
        refs=("branch", "emission_point", "location"),
    ),
    f"GET {ADMIN}/pos-terminals": Route(query=_branch, refs=("branch",)),
    f"GET {ADMIN}/pos-terminals/{{id}}": Route(path=("terminal",)),
    f"PUT {ADMIN}/pos-terminals/{{id}}": Route(
        path=("terminal",),
        body=_terminal("CAJA-01"),
        refs=("emission_point", "location"),
    ),
    f"DELETE {ADMIN}/pos-terminals/{{id}}": Route(path=("terminal",)),
    f"GET {POS}/terminals": Route(
        headers=lambda ids: {"X-Branch-Id": str(ids["branch"])}, refs=("branch",)
    ),
    # Catalog
    f"POST {ADMIN}/categories": Route(
        body=_name("Nueva"), created=f"{ADMIN}/categories/{{}}"
    ),
    f"GET {ADMIN}/categories": Route(),
    f"GET {ADMIN}/categories/{{id}}": Route(path=("category",)),
    f"PUT {ADMIN}/categories/{{id}}": Route(path=("category",), body=_name("Editada")),
    f"DELETE {ADMIN}/categories/{{id}}": Route(path=("category",)),
    f"POST {ADMIN}/units-of-measure": Route(
        body=lambda ids: {"name": "Caja", "symbol": f"{ids['marker']}-cj"},
        created=f"{ADMIN}/units-of-measure/{{}}",
    ),
    f"GET {ADMIN}/units-of-measure": Route(),
    f"GET {ADMIN}/units-of-measure/{{id}}": Route(path=("uom",)),
    f"PUT {ADMIN}/units-of-measure/{{id}}": Route(
        path=("uom",), body=lambda ids: {"name": "Unidad", "symbol": "u2"}
    ),
    f"DELETE {ADMIN}/units-of-measure/{{id}}": Route(path=("uom",)),
    f"POST {ADMIN}/products": Route(body=_product("SKU-NEW"), refs=("category", "uom")),
    f"GET {ADMIN}/products": Route(
        query=lambda ids: {"categoryId": ids["category"]}, refs=("category",)
    ),
    f"GET {ADMIN}/products/{{id}}": Route(path=("product",)),
    f"PUT {ADMIN}/products/{{id}}": Route(
        path=("product",), body=_product("SKU-1"), refs=("category", "uom")
    ),
    f"DELETE {ADMIN}/products/{{id}}": Route(path=("product",)),
    # Inventory
    f"POST {ADMIN}/warehouses": Route(
        body=lambda ids: {
            "branchId": ids["branch"],
            "name": "Bodega",
            "code": f"{ids['marker']}-WH-NEW",
        },
        refs=("branch",),
    ),
    f"GET {ADMIN}/warehouses": Route(query=_branch, refs=("branch",)),
    f"GET {ADMIN}/warehouses/{{id}}": Route(path=("warehouse",)),
    f"PUT {ADMIN}/warehouses/{{id}}": Route(
        path=("warehouse",),
        body=lambda ids: {"name": "Bodega", "code": f"{ids['marker']}-WH1"},
    ),
    f"DELETE {ADMIN}/warehouses/{{id}}": Route(path=("warehouse",)),
    f"POST {ADMIN}/locations": Route(body=_location("NEW"), refs=("warehouse",)),
    f"GET {ADMIN}/locations": Route(query=_warehouse, refs=("warehouse",)),
    f"GET {ADMIN}/locations/{{id}}": Route(path=("location",)),
    f"PUT {ADMIN}/locations/{{id}}": Route(
        path=("location",), body=_location("A1"), refs=("warehouse",)
    ),
    f"DELETE {ADMIN}/locations/{{id}}": Route(path=("location",)),
    f"GET {ADMIN}/stock": Route(
        query=lambda ids: {"productId": ids["product"], "locationId": ids["location"]},
        refs=("product", "location"),
    ),
    f"POST {ADMIN}/movements": Route(
        body=lambda ids: {
            "productId": ids["product"],
            "quantity": 1,
            "type": "IN",
            "locationId": ids["location"],
        },
        refs=("product", "location"),
    ),
    f"GET {ADMIN}/movements": Route(
        query=lambda ids: {"productId": ids["product"]}, refs=("product",)
    ),
    f"POST {ADMIN}/lots": Route(
        body=lambda ids: {
            "productId": ids["product"],
            "lotNumber": f"{ids['marker']}-LOT-NEW",
            "initialQuantity": 1,
        },
        refs=("product",),
    ),
    f"GET {ADMIN}/lots": Route(
        query=lambda ids: {"productId": ids["product"]}, refs=("product",)
    ),
    f"GET {ADMIN}/lots/{{id}}": Route(path=("lot",)),
    f"PUT {ADMIN}/lots/{{id}}": Route(path=("lot",), body=lambda ids: {"notes": "x"}),
    f"POST {ADMIN}/serials": Route(
        body=lambda ids: {
            "productId": ids["product"],
            "serialNumber": f"{ids['marker']}-SN-NEW",
            "lotId": ids["lot"],
            "locationId": ids["location"],
        },
        refs=("product", "lot", "location"),
    ),
    f"GET {ADMIN}/serials": Route(
        query=lambda ids: {"productId": ids["product"]}, refs=("product",)
    ),
    f"GET {ADMIN}/serials/{{id}}": Route(path=("serial",)),
    f"PUT {ADMIN}/serials/{{id}}/status": Route(
        path=("serial",), body=lambda ids: {"status": "reserved"}
    ),
    f"GET {ADMIN}/adjustments": Route(query=_warehouse, refs=("warehouse",)),
    f"POST {ADMIN}/adjustments": Route(
        body=lambda ids: {"warehouseId": ids["warehouse"], "reason": "correction"},
        refs=("warehouse",),
    ),
    f"GET {ADMIN}/adjustments/{{id}}": Route(path=("adjustment",)),
    f"PUT {ADMIN}/adjustments/{{id}}": Route(
        path=("adjustment",), body=lambda ids: {"notes": "x"}
    ),
    f"DELETE {ADMIN}/adjustments/{{id}}": Route(path=("adjustment",)),
    f"POST {ADMIN}/adjustments/{{id}}/confirm": Route(path=("adjustment",)),
    f"POST {ADMIN}/adjustments/{{id}}/cancel": Route(path=("adjustment",)),
    f"POST {ADMIN}/adjustments/{{id}}/items": Route(
        path=("adjustment",),
        body=lambda ids: {
            "productId": ids["product"],
            "locationId": ids["location2"],
            "actualQuantity": 1,
            "lotId": ids["lot"],
        },
        refs=("product", "location2", "lot"),
    ),
    f"GET {ADMIN}/adjustments/{{id}}/items": Route(path=("adjustment",)),
    f"PUT {ADMIN}/adjustment-items/{{id}}": Route(
        path=("adjustment_item",), body=lambda ids: {"actualQuantity": 48}
    ),
    f"DELETE {ADMIN}/adjustment-items/{{id}}": Route(path=("adjustment_item",)),
    f"GET {ADMIN}/transfers": Route(
        query=lambda ids: {"sourceLocationId": ids["location"]}, refs=("location",)
    ),
    f"POST {ADMIN}/transfers": Route(
        body=lambda ids: {
            "sourceLocationId": ids["location"],
            "destinationLocationId": ids["location2"],
        },
        refs=("location", "location2"),
    ),
    f"GET {ADMIN}/transfers/{{id}}": Route(path=("transfer",)),
    f"PUT {ADMIN}/transfers/{{id}}": Route(
        path=("transfer",), body=lambda ids: {"notes": "x"}
    ),
    f"DELETE {ADMIN}/transfers/{{id}}": Route(path=("transfer",)),
    f"POST {ADMIN}/transfers/{{id}}/confirm": Route(path=("transfer",)),
    f"POST {ADMIN}/transfers/{{id}}/receive": Route(path=("transfer",)),
    f"POST {ADMIN}/transfers/{{id}}/cancel": Route(path=("transfer",)),
    f"POST {ADMIN}/transfers/{{id}}/items": Route(
        path=("transfer",),
        body=lambda ids: {
            "productId": ids["product"],
            "quantity": 1,
            "lotId": ids["lot"],
        },
        refs=("product", "lot"),
    ),
    f"GET {ADMIN}/transfers/{{id}}/items": Route(path=("transfer",)),
    f"PUT {ADMIN}/transfer-items/{{id}}": Route(
        path=("transfer_item",), body=lambda ids: {"quantity": 2}
    ),
    f"DELETE {ADMIN}/transfer-items/{{id}}": Route(path=("transfer_item",)),
    f"GET {ADMIN}/alerts/low-stock": Route(query=_warehouse, refs=("warehouse",)),
    f"GET {ADMIN}/alerts/out-of-stock": Route(query=_warehouse, refs=("warehouse",)),
    f"GET {ADMIN}/alerts/reorder-point": Route(query=_warehouse, refs=("warehouse",)),
    f"GET {ADMIN}/alerts/expiring-lots": Route(),
    # Customers
    f"POST {ADMIN}/customers": Route(
        body=lambda ids: {
            "name": f"{ids['marker']} Cliente nuevo",
            "taxId": customer_tax_id(ids["seed"] + 10),
            "taxType": 2,
        },
        created=f"{ADMIN}/customers/{{}}",
    ),
    f"GET {ADMIN}/customers": Route(),
    f"GET {ADMIN}/customers/search/by-tax-id": Route(
        query=lambda ids: {"taxId": ids["tax_id"]}, refs=("tax_id",), needs_query=True
    ),
    f"GET {ADMIN}/customers/{{id}}": Route(path=("customer",)),
    f"PUT {ADMIN}/customers/{{id}}": Route(
        path=("customer",),
        body=lambda ids: {"name": "Cliente", "taxId": ids["tax_id"], "taxType": 2},
    ),
    f"DELETE {ADMIN}/customers/{{id}}": Route(path=("customer",)),
    f"POST {ADMIN}/customers/{{id}}/activate": Route(path=("customer",)),
    f"POST {ADMIN}/customers/{{id}}/deactivate": Route(path=("customer",)),
    f"POST {ADMIN}/customers/{{customer_id}}/contacts": Route(
        path=("customer",), body=_name("Contacto")
    ),
    f"GET {ADMIN}/customers/{{customer_id}}/contacts": Route(path=("customer",)),
    f"GET {ADMIN}/customer-contacts/{{id}}": Route(path=("customer_contact",)),
    f"PUT {ADMIN}/customer-contacts/{{id}}": Route(
        path=("customer_contact",), body=_name("Contacto")
    ),
    f"DELETE {ADMIN}/customer-contacts/{{id}}": Route(path=("customer_contact",)),
    # Suppliers
    f"POST {ADMIN}/suppliers": Route(
        body=lambda ids: {
            "name": f"{ids['marker']} Proveedor nuevo",
            "taxId": supplier_tax_id(ids["seed"] + 20),
            "taxType": 1,
        },
        created=f"{ADMIN}/suppliers/{{}}",
    ),
    f"GET {ADMIN}/suppliers": Route(),
    f"GET {ADMIN}/suppliers/{{id}}": Route(path=("supplier",)),
    f"PUT {ADMIN}/suppliers/{{id}}": Route(
        path=("supplier",),
        body=lambda ids: {
            "name": "Proveedor",
            "taxId": supplier_tax_id(ids["seed"]),
            "taxType": 1,
        },
    ),
    f"DELETE {ADMIN}/suppliers/{{id}}": Route(path=("supplier",)),
    f"POST {ADMIN}/suppliers/{{id}}/activate": Route(path=("supplier",)),
    f"POST {ADMIN}/suppliers/{{id}}/deactivate": Route(path=("supplier",)),
    f"POST {ADMIN}/suppliers/{{supplier_id}}/contacts": Route(
        path=("supplier",), body=_name("Vendedor")
    ),
    f"GET {ADMIN}/suppliers/{{supplier_id}}/contacts": Route(path=("supplier",)),
    # Another product: the supplier already lists the first one
    f"POST {ADMIN}/suppliers/{{supplier_id}}/products": Route(
        path=("supplier",),
        body=lambda ids: {"productId": ids["product_out"], "purchasePrice": "1.00"},
        refs=("product_out",),
    ),
    f"GET {ADMIN}/suppliers/{{supplier_id}}/products": Route(path=("supplier",)),
    f"GET {ADMIN}/supplier-contacts/{{id}}": Route(path=("supplier_contact",)),
    f"PUT {ADMIN}/supplier-contacts/{{id}}": Route(
        path=("supplier_contact",), body=_name("Vendedor")
    ),
    f"DELETE {ADMIN}/supplier-contacts/{{id}}": Route(path=("supplier_contact",)),
    f"GET {ADMIN}/supplier-products/{{id}}": Route(path=("supplier_product",)),
    f"PUT {ADMIN}/supplier-products/{{id}}": Route(
        path=("supplier_product",),
        body=lambda ids: {"productId": ids["product"], "purchasePrice": "4.00"},
        refs=("product",),
    ),
    f"DELETE {ADMIN}/supplier-products/{{id}}": Route(path=("supplier_product",)),
    f"GET {ADMIN}/supplier-products/by-product/{{product_id}}": Route(
        path=("product",)
    ),
    # Purchasing
    f"POST {ADMIN}/purchase-orders": Route(
        body=lambda ids: {"supplierId": ids["supplier"]}, refs=("supplier",)
    ),
    f"GET {ADMIN}/purchase-orders": Route(
        query=lambda ids: {"supplierId": ids["supplier"]}, refs=("supplier",)
    ),
    f"GET {ADMIN}/purchase-orders/{{id}}": Route(path=("po_draft",)),
    f"PUT {ADMIN}/purchase-orders/{{id}}": Route(
        path=("po_draft",),
        body=lambda ids: {"supplierId": ids["supplier"]},
        refs=("supplier",),
    ),
    f"DELETE {ADMIN}/purchase-orders/{{id}}": Route(path=("po_draft",)),
    f"POST {ADMIN}/purchase-orders/{{id}}/send": Route(path=("po_draft",)),
    f"POST {ADMIN}/purchase-orders/{{id}}/cancel": Route(path=("po_draft",)),
    f"POST {ADMIN}/purchase-orders/{{id}}/receive": Route(
        path=("po_sent",), body=_receive, refs=("po_sent_item", "location")
    ),
    f"GET {ADMIN}/purchase-orders/{{id}}/items": Route(path=("po_sent",)),
    f"GET {ADMIN}/purchase-orders/{{id}}/receipts": Route(path=("po_sent",)),
    f"POST {ADMIN}/purchase-order-items": Route(
        body=lambda ids: {
            "purchaseOrderId": ids["po_draft"],
            "productId": ids["product_out"],
            "quantityOrdered": 1,
            "unitCost": "1.00",
        },
        refs=("po_draft", "product_out"),
    ),
    f"PUT {ADMIN}/purchase-order-items/{{id}}": Route(
        path=("po_draft_item",),
        body=lambda ids: {"quantityOrdered": 4, "unitCost": "5.00"},
    ),
    f"DELETE {ADMIN}/purchase-order-items/{{id}}": Route(path=("po_draft_item",)),
    # Sales (admin)
    f"GET {ADMIN}/sales": Route(
        query=lambda ids: {"customerId": ids["customer"]}, refs=("customer",)
    ),
    f"GET {ADMIN}/sales/{{sale_id}}": Route(path=("sale",)),
    f"GET {ADMIN}/sales/{{sale_id}}/items": Route(path=("sale",)),
    f"GET {ADMIN}/sales/{{sale_id}}/payments": Route(path=("sale",)),
    f"POST {ADMIN}/sales/{{sale_id}}/request-invoice": Route(path=("sale",)),
    # Users: global identities, members per tenant
    f"GET {ADMIN}/users": Route(),
    f"GET {ADMIN}/audit-log": Route(),
    f"POST {ADMIN}/users": Route(
        body=lambda ids: {
            "username": f"{ids['marker'].lower()}-new",
            "email": f"{ids['marker'].lower()}-new@test.local",
            "password": "Member-Pass-2026!",
            "role": 4,
        },
        created=f"{ADMIN}/users/{{}}",
    ),
    f"GET {ADMIN}/users/{{user_id}}": Route(path=("user",)),
    f"GET {ADMIN}/users/{{user_id}}/branches": Route(path=("user",)),
    f"PUT {ADMIN}/users/{{user_id}}/branches": Route(
        path=("user",),
        body=lambda ids: {"branchIds": [ids["branch"]]},
        refs=("branch",),
    ),
    f"PUT {ADMIN}/users/{{user_id}}/role": Route(
        path=("user",), body=lambda ids: {"role": 3}
    ),
    f"PUT {ADMIN}/users/{{user_id}}/profile": Route(
        path=("user",), body=lambda ids: {"fullName": "Otro nombre"}
    ),
    f"POST {ADMIN}/users/{{user_id}}/activate": Route(path=("user",)),
    f"POST {ADMIN}/users/{{user_id}}/deactivate": Route(path=("user",)),
    f"POST {ADMIN}/users/{{user_id}}/reset-password": Route(
        path=("user",), body=lambda ids: {"newPassword": "Reset-Pass-2026!"}
    ),
    # Reports
    f"GET {ADMIN}/reports/inventory/valuation": Route(
        query=_warehouse, refs=("warehouse",)
    ),
    f"GET {ADMIN}/reports/inventory/rotation": Route(
        query=_warehouse, refs=("warehouse",)
    ),
    f"GET {ADMIN}/reports/inventory/movements": Route(
        query=lambda ids: {
            "productId": ids["product"],
            "warehouseId": ids["warehouse"],
        },
        refs=("product", "warehouse"),
    ),
    f"GET {ADMIN}/reports/inventory/summary": Route(
        query=_warehouse, refs=("warehouse",)
    ),
    f"GET {ADMIN}/dashboard": Route(),
    # POS
    f"POST {POS}/sales": Route(
        body=lambda ids: {"customerId": ids["customer"]},
        headers=_at_terminal(),
        refs=("customer", "branch", "terminal"),
    ),
    f"POST {POS}/sales/quick": Route(
        body=lambda ids: {
            "customerId": ids["customer"],
            "items": [{"productId": ids["product"], "quantity": 1}],
            "payments": [{"amount": "11.50", "paymentMethod": "CASH"}],
        },
        headers=_at_terminal(),
        refs=("customer", "product", "branch", "terminal"),
    ),
    f"GET {POS}/sales/parked": Route(
        headers=_at_terminal(), refs=("branch", "terminal")
    ),
    f"GET {POS}/sales/{{sale_id}}": Route(
        path=("pos_draft",), headers=_in_branch, refs=("branch",)
    ),
    f"POST {POS}/sales/{{sale_id}}/items": Route(
        path=("pos_draft",),
        body=lambda ids: {
            "productId": ids["product"],
            "quantity": 1,
            "unitPrice": "10.00",
        },
        headers=_in_branch,
        refs=("product",),
    ),
    f"GET {POS}/sales/{{sale_id}}/items": Route(
        path=("pos_draft",), headers=_in_branch, refs=("branch",)
    ),
    # An item of A's sale vs one of B's
    f"PUT {POS}/sales/{{sale_id}}/items/{{item_id}}": Route(
        path=("pos_draft", "pos_draft_item"),
        body=lambda ids: {"quantity": 2},
        headers=_in_branch,
        refs=("pos_draft_item",),
    ),
    f"DELETE {POS}/sales/{{sale_id}}/items/{{item_id}}": Route(
        path=("pos_draft", "pos_draft_item"), headers=_in_branch
    ),
    f"PUT {POS}/sales/{{sale_id}}/items/{{item_id}}/price": Route(
        path=("pos_draft", "pos_draft_item"),
        body=lambda ids: {"newPrice": "9.00", "reason": "Cliente frecuente"},
        headers=_in_branch,
    ),
    f"POST {POS}/sales/{{sale_id}}/confirm": Route(
        path=("pos_draft",), headers=_in_branch
    ),
    f"POST {POS}/sales/{{sale_id}}/cancel": Route(
        path=("pos_draft",), headers=_in_branch
    ),
    f"POST {POS}/sales/{{sale_id}}/park": Route(
        path=("pos_draft",), headers=_in_branch
    ),
    f"POST {POS}/sales/{{sale_id}}/resume": Route(
        path=("pos_draft",), headers=_in_branch
    ),
    f"POST {POS}/sales/{{sale_id}}/discount": Route(
        path=("pos_draft",),
        body=lambda ids: {"discountType": "AMOUNT", "discountValue": "1.00"},
        headers=_in_branch,
    ),
    f"POST {POS}/sales/{{sale_id}}/payments": Route(
        path=("pos_draft",), body=_payment("1.00"), headers=_in_branch
    ),
    f"GET {POS}/sales/{{sale_id}}/payments": Route(
        path=("sale",), headers=_in_branch, refs=("branch",)
    ),
    f"GET {POS}/sales/{{sale_id}}/receipt": Route(
        path=("sale",), headers=_in_branch, refs=("branch",)
    ),
    # At the terminal without a shift: B's terminal or branch look missing
    f"POST {POS}/shifts/open": Route(
        body=lambda ids: {"openingBalance": "0"},
        headers=_at_terminal("terminal2"),
        refs=("branch", "terminal2"),
    ),
    f"POST {POS}/shifts/{{shift_id}}/close": Route(
        path=("shift",),
        body=lambda ids: {"closingBalance": "100.00"},
        headers=_in_branch,
    ),
    f"GET {POS}/shifts/active": Route(
        headers=_at_terminal(), refs=("branch", "terminal")
    ),
    f"GET {POS}/shifts/{{shift_id}}": Route(path=("shift",)),
    f"GET {POS}/shifts": Route(query=_placement, refs=("branch", "terminal")),
    f"POST {POS}/shifts/{{shift_id}}/cash-movements": Route(
        path=("shift",),
        body=lambda ids: {"type": "OUT", "amount": "1.00"},
        headers=_in_branch,
    ),
    f"GET {POS}/shifts/{{shift_id}}/cash-movements": Route(
        path=("shift",), headers=_in_branch, refs=("branch",)
    ),
    f"GET {POS}/shifts/{{shift_id}}/cash-summary": Route(
        path=("shift",), headers=_in_branch, refs=("branch",)
    ),
    f"GET {POS}/products": Route(),
    f"GET {POS}/products/search": Route(
        query=lambda ids: {"term": ids["sku"]}, refs=("sku",), needs_query=True
    ),
    f"GET {POS}/products/{{id}}": Route(path=("product",)),
    f"POST {POS}/customers": Route(
        body=lambda ids: {
            "name": f"{ids['marker']} Cliente POS",
            "taxId": customer_tax_id(ids["seed"] + 30),
            "taxType": 2,
        },
        created=f"{POS}/customers/{{}}",
    ),
    f"GET {POS}/customers": Route(),
    f"GET {POS}/customers/search/by-tax-id": Route(
        query=lambda ids: {"taxId": ids["tax_id"]}, refs=("tax_id",), needs_query=True
    ),
    f"GET {POS}/customers/{{id}}": Route(path=("customer",)),
    f"POST {POS}/refunds": Route(
        body=lambda ids: {
            "originalSaleId": ids["sale"],
            "items": [{"saleItemId": ids["sale_item"], "quantity": 1}],
        },
        headers=_at_terminal(),
        refs=("sale", "sale_item", "branch", "terminal"),
    ),
    f"POST {POS}/refunds/{{refund_id}}/process": Route(
        path=("refund",),
        body=lambda ids: {"payments": [_payment("11.50")(ids)]},
        headers=_in_branch,
    ),
    f"POST {POS}/refunds/{{refund_id}}/cancel": Route(
        path=("refund",), headers=_in_branch
    ),
    f"GET {POS}/refunds/{{refund_id}}": Route(path=("refund",)),
    f"GET {POS}/refunds": Route(
        query=lambda ids: {"saleId": ids["sale"], **_placement(ids)},
        refs=("sale", "branch", "terminal"),
    ),
    f"GET {POS}/reports/x-report": Route(
        query=lambda ids: {"shiftId": ids["shift"]}, refs=("shift",), needs_query=True
    ),
    f"GET {POS}/reports/z-report": Route(
        query=lambda ids: {"shiftId": ids["shift"]}, refs=("shift",), needs_query=True
    ),
    f"GET {POS}/reports/daily": Route(query=_placement, refs=("branch", "terminal")),
    f"GET {POS}/reports/by-payment-method": Route(
        query=_placement, refs=("branch", "terminal")
    ),
    # Platform: no tenant data, or covered elsewhere
    "POST /api/auth/login": Route(exempt="before any tenant (test_tenancy.py)"),
    "POST /api/auth/select-tenant": Route(
        exempt="checks the membership of the chosen tenant (test_tenancy.py)"
    ),
    "POST /api/auth/refresh": Route(exempt="keeps the session's tenant"),
    "POST /api/auth/logout": Route(exempt="revokes the caller's session"),
    "GET /api/auth/me": Route(
        exempt="the caller's own tenants and branches (test_tenancy.py, "
        "test_organization.py)"
    ),
    "POST /api/auth/change-password": Route(exempt="the caller's own password"),
    "GET /health/live": Route(exempt="no data"),
    "GET /health/ready": Route(exempt="no data"),
    "GET /": Route(exempt="docs"),
    "GET /docs": Route(exempt="docs"),
    "GET /docs/admin": Route(exempt="docs"),
    "GET /docs/pos": Route(exempt="docs"),
    "GET /openapi/admin.json": Route(exempt="docs"),
    "GET /openapi/pos.json": Route(exempt="docs"),
}


def kind(key: str, route: Route) -> str:
    method = key.split(" ", 1)[0]
    if route.exempt:
        return "exempt"
    if route.path:
        return "foreign"
    if method == "GET":
        return "search" if route.needs_query else "listing"
    if route.refs:
        return "references"
    return "creates"


def keys(*kinds: str) -> list[str]:
    return [key for key, route in ROUTES.items() if kind(key, route) in kinds]


def with_refs() -> list[str]:
    """The reads first: a write's own call changes A's data"""
    found = [key for key, route in ROUTES.items() if route.refs and not route.exempt]
    return sorted(found, key=lambda key: not key.startswith("GET "))
