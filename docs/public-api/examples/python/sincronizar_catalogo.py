"""Sincroniza productos, listas de precios y stock (guía "Sincronizar catálogo y
stock").

La primera vez trae todo; después, solo lo cambiado desde la sincronización
anterior, cuyo momento se guarda en FACLAB_SYNC_STATE (por defecto
.faclab-sync). Como `updatedSince` es inclusivo, una fila del borde puede
repetirse: se guarda por id, nunca se inserta dos veces.

    python sincronizar_catalogo.py
"""

import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from faclab import Faclab

STATE = Path(os.environ.get("FACLAB_SYNC_STATE", ".faclab-sync"))


def main() -> int:
    api = Faclab()
    since = STATE.read_text().strip() if STATE.exists() else None
    # El momento en que empieza: la próxima vez se pide lo cambiado desde aquí
    started = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    params = {"updatedSince": since} if since else {}
    products = {p["id"]: p for p in api.pages("/api/v1/products", **params)}
    print(f"productos {'cambiados' if since else 'en total'}: {len(products)}")
    for product in list(products.values())[:3]:
        presentations = ", ".join(
            f"{p['name']} x{p['factor']} a {p['salePrice'] or '-'}"
            for p in product["presentations"]
        )
        print(f"  {product['sku']} {product['name']}: {presentations}")

    price_lists = list(api.pages("/api/v1/price-lists"))
    print(f"listas de precios: {', '.join(pl['name'] for pl in price_lists)}")

    for branch in api.get("/api/v1/branches")["data"]:
        available: dict[str, Decimal] = {}
        for row in api.pages("/api/v1/stock", branchId=branch["id"]):
            available[row["sku"]] = available.get(row["sku"], Decimal(0)) + Decimal(
                row["available"]
            )
        with_stock = sum(1 for quantity in available.values() if quantity > 0)
        print(
            f"sucursal {branch['code']} {branch['name']}: "
            f"{with_stock} productos con stock"
        )

    STATE.write_text(started)
    print(f"próxima sincronización: updatedSince={started}")
    if not since and not products:
        print("la empresa no tiene productos", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
