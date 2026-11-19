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
from faclab import Faclab

api = Faclab()
for product in api.pages("/api/v1/products", updatedSince="2026-11-18T15:00:00Z"):
    guardar_por_id(product)
```

Completo, con el estado entre corridas:
[sincronizar_catalogo.py](examples/python/sincronizar_catalogo.py),
[sincronizar-catalogo.mjs](examples/javascript/sincronizar-catalogo.mjs) y, para probar a mano,
[catalogo-y-stock.sh](examples/curl/catalogo-y-stock.sh).

## Productos

`GET /api/v1/products` (`products:read`): filtros `sku`, `barcode` (de cualquier presentación) y
`search` (nombre, SKU o código de barras). Cada producto trae su unidad (`unitSymbol`,
`quantityDecimals`), su precio sin IVA (`salePrice`), su código de IVA (`taxCode`) y sus
**presentaciones** (caja de 100, rollo de 50 m) con su factor y su precio. Cambiar una presentación
actualiza el `updatedAt` del producto. El precio de compra no es público.

## Listas de precios

`GET /api/v1/price-lists` y `GET /api/v1/price-lists/{id}/items` (`prices:read`). Una venta toma el
precio de la lista del cliente; si no tiene, la de la sucursal, y si no, la general. Dentro de una
lista toma el ítem de la presentación con el `minQuantity` más alto que no pase de la cantidad.

## Stock

`GET /api/v1/stock` (`stock:read`): una fila por producto y ubicación de las bodegas de una sucursal,
en unidades base. `available` es lo que una venta puede tomar: lo que hay menos lo reservado por
transferencias. `branchId` es obligatorio salvo que el cliente opere en una sola sucursal
(400 `BRANCH_REQUIRED`). El disponible de una sucursal es la suma de `available` de sus filas.

## Sin consultar a cada rato

En vez de sincronizar cada pocos minutos, suscríbete por webhook (ver **Webhooks**):

- `product.updated` llega cuando se crea un producto o cambia lo que muestra la API (precio,
  presentaciones…), con `changedFields`. Pide ese producto con `GET /api/v1/products/{id}`.
- `stock.changed` llega cuando cambia el disponible de un producto en una sucursal, con el nuevo
  `available`. Como mucho llega uno por producto y sucursal cada 30 segundos.

Una sincronización con `updatedSince` una vez al día sigue siendo buena idea: recupera lo que se
haya perdido mientras tu receptor estaba caído.
