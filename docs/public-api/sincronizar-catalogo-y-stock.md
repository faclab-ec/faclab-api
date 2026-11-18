# Sincronizar catálogo y stock

Los listados devuelven páginas en un **orden estable**: el id desempata siempre, así una página
nunca repite ni salta filas de la anterior.

- `limit` de 1 a 200 (50 por defecto) y `offset`; `meta.pagination.total` dice cuántas filas hay.
- `sort=campo` o `sort=-campo` entre los campos de cada recurso (otro: 422 `VALIDATION_ERROR` con
  `field: "sort"`).
- `updatedSince` (ISO 8601, inclusivo) devuelve lo cambiado desde ese momento y, sin `sort`, en orden
  de `updatedAt` y luego id.

## Una sincronización

1. Guarda el momento en que empiezas (`T`).
2. Pide las páginas con `updatedSince` igual al `T` de la sincronización anterior hasta que una página
   venga con menos de `limit` filas.
3. Guarda `T` para la próxima vez.

Como `updatedSince` es inclusivo puede repetirse alguna fila del borde: actualiza por id, no
insertes.

```python
import httpx

def products_changed_since(token: str, since: str):
    offset = 0
    while True:
        page = httpx.get(
            "https://api.<dominio>/api/v1/products",
            params={"updatedSince": since, "limit": 200, "offset": offset},
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        yield from page["data"]
        if len(page["data"]) < 200:
            return
        offset += 200
```

## Productos

`GET /api/v1/products` (`products:read`): filtros `sku`, `barcode` (de cualquier presentación) y
`search` (nombre, SKU o código de barras). Cada producto trae su unidad (`unitSymbol`,
`quantityDecimals`) y sus **presentaciones** (caja de 100, rollo de 50 m) con su factor y precio:
cambiar una presentación actualiza el `updatedAt` del producto. El precio de compra no es público.

## Listas de precios

`GET /api/v1/price-lists` y `GET /api/v1/price-lists/{id}/items` (`prices:read`). Una venta toma el
precio de la lista del cliente, si no la de la sucursal, si no la general; dentro de una lista, el
ítem de la presentación con el `minQuantity` más alto hasta la cantidad.

## Stock

`GET /api/v1/stock` (`stock:read`): una fila por producto y ubicación de las bodegas de una sucursal,
en unidades base. `available` es lo que una venta puede tomar (lo que hay menos lo reservado por
transferencias). `branchId` es obligatorio salvo que el cliente opere en una sola sucursal
(400 `BRANCH_REQUIRED`). Para el disponible de una sucursal, suma `available` de sus filas.
