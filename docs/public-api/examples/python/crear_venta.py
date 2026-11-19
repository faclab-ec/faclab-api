"""Registra un pedido pagado en línea como venta de Faclab (guía "Ventas desde un
ecommerce"), lo reintenta con la misma clave y luego lo anula.

1. Dónde vender: la sucursal, su punto de emisión y una ubicación con stock.
2. Qué vender: un producto con stock y su precio con IVA, el que cobra Faclab.
3. La venta, con su `Idempotency-Key`; el reintento recibe la misma respuesta.
4. Buscarla por `externalReference` y anularla (con la factura en camino,
   Faclab responde INVOICE_IN_PROGRESS: se anula con una nota de crédito).

    python crear_venta.py
"""

import sys
import uuid
from decimal import Decimal

from faclab import Faclab, FaclabError, line_total

# El consumidor final factura hasta este total; con más hace falta el cliente
FINAL_CONSUMER_LIMIT = Decimal("50")


def choose_product(api: Faclab, branch: dict) -> tuple[dict, dict]:
    """Un producto activo con stock en una ubicación de la sucursal"""
    for row in api.pages("/api/v1/stock", branchId=branch["id"]):
        if Decimal(row["available"]) < 1:
            continue
        product = api.get(f"/api/v1/products/{row['productId']}")["data"]
        if product["isActive"] and not product["isService"]:
            price = line_total(product["salePrice"], "1", product["taxCode"])
            if price <= FINAL_CONSUMER_LIMIT:
                return row, product
    raise SystemExit(f"la sucursal {branch['code']} no tiene productos con stock")


def main() -> int:
    api = Faclab()
    branch = next(b for b in api.get("/api/v1/branches")["data"] if b["emissionPoints"])
    stock, product = choose_product(api, branch)
    total = line_total(product["salePrice"], "1", product["taxCode"])
    order = f"WEB-{uuid.uuid4().hex[:8].upper()}"
    body = {
        "emissionPointId": branch["emissionPoints"][0]["id"],
        "locationId": stock["locationId"],
        "externalReference": order,
        "items": [{"productId": product["id"], "quantity": "1"}],
        "payments": [
            {"method": "TRANSFER", "amount": str(total), "reference": f"pago-{order}"}
        ],
    }

    # Una clave por pedido, la misma en cada reintento de ese pedido
    key = str(uuid.uuid4())
    created = api.post(
        "/api/v1/sales", body, branch_id=branch["id"], idempotency_key=key
    )
    sale = created.json()["data"]
    print(
        f"venta {sale['number']} ({order}): {product['sku']} por {sale['total']}, "
        f"factura {sale['invoiceStatus']}"
    )
    assert created.status_code == 201, created.status_code
    assert Decimal(sale["total"]) == total, (sale["total"], total)

    retried = api.post(
        "/api/v1/sales", body, branch_id=branch["id"], idempotency_key=key
    )
    assert retried.headers.get("Idempotent-Replayed") == "true"
    assert retried.json()["data"]["id"] == sale["id"]
    print("reintento con la misma clave: la misma venta (Idempotent-Replayed)")

    found = api.get("/api/v1/sales", externalReference=order)["data"]
    assert [s["id"] for s in found] == [sale["id"]]

    try:
        api.post(
            f"/api/v1/sales/{sale['id']}/cancel",
            {"reason": "Pedido anulado en la tienda"},
        )
        print(f"venta {sale['number']} anulada: el stock vuelve")
    except FaclabError as error:
        if error.code not in ("INVOICE_IN_PROGRESS", "CREDIT_NOTE_REQUIRED"):
            raise
        print(f"venta {sale['number']} con factura en camino: {error.code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
