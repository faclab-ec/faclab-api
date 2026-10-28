# Referencia de API

La API esta dividida en dos superficies:

- **Admin API** — prefijo `/api/admin` — gestion completa del back-office
- **POS API** — prefijo `/api/pos` — operaciones del punto de venta

La documentacion interactiva (Scalar) esta disponible cuando `DOCS_ENABLED=true`:

| URL | Descripcion |
|---|---|
| `http://localhost:3000/docs` | Todos los endpoints |
| `http://localhost:3000/docs/admin` | Solo Admin |
| `http://localhost:3000/docs/pos` | Solo POS |

---

## Admin API

### Sucursales — `/api/admin/branches`

Lectura con `organization:read`; crear, editar y borrar con `organization:write` (solo ADMIN).

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/branches` | Crear sucursal (`establishmentCode` de tres digitos, unico por empresa) |
| `GET` | `/api/admin/branches` | Listar sucursales; `isActive` |
| `GET` | `/api/admin/branches/{id}` | Obtener por ID |
| `PUT` | `/api/admin/branches/{id}` | Actualizar codigo, nombre, direccion o estado (`isMain` no cambia) |
| `DELETE` | `/api/admin/branches/{id}` | Eliminar (no la matriz: `MAIN_BRANCH_DELETION`; no una en uso: `RECORD_IN_USE`) |

### Puntos de Emision — `/api/admin/emission-points`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/emission-points` | Crear punto de emision (`branchId`, `code` de tres digitos, unico por sucursal) |
| `GET` | `/api/admin/emission-points` | Listar; `branchId`, `isActive` |
| `GET` | `/api/admin/emission-points/{id}` | Obtener por ID |
| `PUT` | `/api/admin/emission-points/{id}` | Actualizar codigo, nombre o estado (la sucursal no cambia) |
| `DELETE` | `/api/admin/emission-points/{id}` | Eliminar (no uno con terminales: `RECORD_IN_USE`) |

### Terminales POS — `/api/admin/pos-terminals`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/pos-terminals` | Crear terminal: punto de emision y ubicacion por defecto de la misma sucursal (`EMISSION_POINT_OUTSIDE_BRANCH`, `LOCATION_OUTSIDE_BRANCH`) |
| `GET` | `/api/admin/pos-terminals` | Listar; `branchId`, `isActive` |
| `GET` | `/api/admin/pos-terminals/{id}` | Obtener por ID |
| `PUT` | `/api/admin/pos-terminals/{id}` | Actualizar punto de emision, ubicacion, codigo, nombre o estado (la sucursal no cambia) |
| `DELETE` | `/api/admin/pos-terminals/{id}` | Eliminar |

### Encabezado `X-Branch-Id`

La sucursal de la operacion. Toda ruta autenticada que lo recibe lo valida: 422
`INVALID_BRANCH_HEADER` si no es un id, 403 `BRANCH_ACCESS_DENIED` si el usuario esta limitado a
otras sucursales (claim `bids`). Las rutas de sucursal lo exigen (`BRANCH_REQUIRED`, 400):
`GET /api/pos/terminals` y, desde S2.6, las operaciones del POS. Las que empiezan en una terminal
(abrir turno, turno activo, crear venta, venta rápida, aparcadas, crear devolución) piden además
`X-Terminal-Id` (`TERMINAL_REQUIRED`, 400; `INVALID_TERMINAL_HEADER`, 422), y una venta, un turno o
una devolución de otra sucursal responde 404. Detalle en `pos-api-spec.md` §0.

### Categorias — `/api/admin/categories`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/categories` | Crear categoria |
| `GET` | `/api/admin/categories` | Listar categorias |
| `GET` | `/api/admin/categories/{id}` | Obtener por ID |
| `PUT` | `/api/admin/categories/{id}` | Actualizar |
| `DELETE` | `/api/admin/categories/{id}` | Eliminar |

### Unidades de Medida — `/api/admin/units-of-measure`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/units-of-measure` | Crear unidad |
| `GET` | `/api/admin/units-of-measure` | Listar unidades |
| `GET` | `/api/admin/units-of-measure/{id}` | Obtener por ID |
| `PUT` | `/api/admin/units-of-measure/{id}` | Actualizar |
| `DELETE` | `/api/admin/units-of-measure/{id}` | Eliminar |

### Productos — `/api/admin/products`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/products` | Crear producto |
| `GET` | `/api/admin/products` | Listar con paginacion; `categoryId`, `search` (nombre o SKU que contienen el texto, o código de barras exacto) |
| `GET` | `/api/admin/products/{id}` | Obtener por ID |
| `PUT` | `/api/admin/products/{id}` | Actualizar |
| `DELETE` | `/api/admin/products/{id}` | Eliminar |

### Almacenes — `/api/admin/warehouses`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/warehouses` | Crear almacen en una sucursal (`branchId` obligatorio) |
| `GET` | `/api/admin/warehouses` | Listar almacenes; `branchId`, `isActive` |
| `GET` | `/api/admin/warehouses/{id}` | Obtener por ID |
| `PUT` | `/api/admin/warehouses/{id}` | Actualizar (la sucursal no cambia) |
| `DELETE` | `/api/admin/warehouses/{id}` | Eliminar |

### Ubicaciones — `/api/admin/locations`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/locations` | Crear ubicacion |
| `GET` | `/api/admin/locations` | Listar ubicaciones |
| `GET` | `/api/admin/locations/{id}` | Obtener por ID |
| `PUT` | `/api/admin/locations/{id}` | Actualizar |
| `DELETE` | `/api/admin/locations/{id}` | Eliminar |

### Stock — `/api/admin/stock`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `GET` | `/api/admin/stock` | Listar niveles de stock |
| `GET` | `/api/admin/stock/{id}` | Obtener por ID |
| `GET` | `/api/admin/stock/product/{product_id}` | Stock por producto |

> El stock se actualiza automaticamente mediante eventos de dominio — no existe endpoint de escritura directa.

### Movimientos — `/api/admin/movements`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/movements` | Crear movimiento manual (IN/OUT), sin documento (`referenceType`/`referenceId` solo los llenan ventas, devoluciones, ajustes, transferencias y compras); un OUT solo toma lo disponible (`INSUFFICIENT_STOCK`) |
| `GET` | `/api/admin/movements` | Listar movimientos; `productId`, `type`, `fromDate` y `toDate` (fecha y hora, ambos incluidos) |
| `GET` | `/api/admin/movements/{id}` | Obtener por ID |

### Lotes — `/api/admin/lots`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/lots` | Crear lote |
| `GET` | `/api/admin/lots` | Listar lotes |
| `GET` | `/api/admin/lots/{id}` | Obtener por ID |
| `PUT` | `/api/admin/lots/{id}` | Actualizar lote |

### Numeros de Serie — `/api/admin/serials`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/serials` | Registrar serial |
| `GET` | `/api/admin/serials` | Listar seriales |
| `GET` | `/api/admin/serials/{id}` | Obtener por ID |
| `PUT` | `/api/admin/serials/{id}` | Actualizar estado |

### Clientes — `/api/admin/customers`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/customers` | Crear cliente |
| `GET` | `/api/admin/customers` | Listar clientes; `search` (nombre o identificación que contienen el texto) |
| `GET` | `/api/admin/customers/{id}` | Obtener por ID |
| `GET` | `/api/admin/customers/tax-id/{tax_id}` | Buscar por RUC |
| `PUT` | `/api/admin/customers/{id}` | Actualizar |
| `DELETE` | `/api/admin/customers/{id}` | Eliminar |
| `POST` | `/api/admin/customers/{id}/activate` | Activar |
| `POST` | `/api/admin/customers/{id}/deactivate` | Desactivar |

### Contactos de Clientes — `/api/admin/customer-contacts`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/customer-contacts` | Crear contacto |
| `GET` | `/api/admin/customer-contacts/{id}` | Obtener por ID |
| `PUT` | `/api/admin/customer-contacts/{id}` | Actualizar |
| `DELETE` | `/api/admin/customer-contacts/{id}` | Eliminar |
| `GET` | `/api/admin/customer-contacts/customer/{id}` | Contactos por cliente |

### Proveedores — `/api/admin/suppliers`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/suppliers` | Crear proveedor |
| `GET` | `/api/admin/suppliers` | Listar proveedores; `isActive`, `search` (nombre o identificación que contienen el texto) |
| `GET` | `/api/admin/suppliers/{id}` | Obtener por ID |
| `PUT` | `/api/admin/suppliers/{id}` | Actualizar |
| `DELETE` | `/api/admin/suppliers/{id}` | Eliminar |

### Contactos de Proveedores — `/api/admin/supplier-contacts`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/supplier-contacts` | Crear contacto |
| `GET` | `/api/admin/supplier-contacts/{id}` | Obtener por ID |
| `PUT` | `/api/admin/supplier-contacts/{id}` | Actualizar |
| `DELETE` | `/api/admin/supplier-contacts/{id}` | Eliminar |
| `GET` | `/api/admin/supplier-contacts/supplier/{id}` | Contactos por proveedor |

### Productos de Proveedor — `/api/admin/supplier-products`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/supplier-products` | Vincular producto a proveedor |
| `GET` | `/api/admin/supplier-products/{id}` | Obtener por ID |
| `PUT` | `/api/admin/supplier-products/{id}` | Actualizar precio/referencia |
| `DELETE` | `/api/admin/supplier-products/{id}` | Desvincular |
| `GET` | `/api/admin/supplier-products/supplier/{id}` | Productos por proveedor |

### Ordenes de Compra — `/api/admin/purchase-orders`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/purchase-orders` | Crear orden de compra |
| `GET` | `/api/admin/purchase-orders` | Listar ordenes |
| `GET` | `/api/admin/purchase-orders/{id}` | Obtener por ID |
| `POST` | `/api/admin/purchase-orders/{id}/receive` | Recepcionar mercaderia |

### Items de Orden de Compra — `/api/admin/purchase-order-items`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/purchase-order-items` | Agregar item |
| `GET` | `/api/admin/purchase-order-items/{id}` | Obtener por ID |
| `PUT` | `/api/admin/purchase-order-items/{id}` | Actualizar cantidad/precio |
| `DELETE` | `/api/admin/purchase-order-items/{id}` | Eliminar item |

### Ventas (vista admin) — `/api/admin/sales`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/sales` | Crear venta (DRAFT) |
| `GET` | `/api/admin/sales` | Listar ventas |
| `GET` | `/api/admin/sales/{id}` | Obtener por ID |
| `POST` | `/api/admin/sales/{id}/items` | Agregar item |
| `DELETE` | `/api/admin/sales/{id}/items/{item_id}` | Remover item |
| `POST` | `/api/admin/sales/{id}/payments` | Registrar pago |
| `GET` | `/api/admin/sales/{id}/payments` | Listar pagos |
| `GET` | `/api/admin/sales/{id}/items` | Listar items |
| `POST` | `/api/admin/sales/{id}/request-invoice` | Reenviar una venta `CONFIRMED` a faclab-invoicing |

> La confirmacion y anulacion se realizan desde el POS (`/api/pos/sales`).

### Ajustes de Inventario — `/api/admin/adjustments`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/adjustments` | Crear ajuste |
| `GET` | `/api/admin/adjustments` | Listar ajustes |
| `GET` | `/api/admin/adjustments/{id}` | Obtener por ID |
| `PUT` | `/api/admin/adjustments/{id}` | Actualizar |

### Items de Ajuste — `/api/admin/adjustment-items`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/adjustment-items` | Agregar item de ajuste |
| `GET` | `/api/admin/adjustment-items/{id}` | Obtener por ID |
| `PUT` | `/api/admin/adjustment-items/{id}` | Actualizar |
| `DELETE` | `/api/admin/adjustment-items/{id}` | Eliminar |

### Transferencias — `/api/admin/transfers`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/transfers` | Crear transferencia |
| `GET` | `/api/admin/transfers` | Listar transferencias |
| `GET` | `/api/admin/transfers/{id}` | Obtener por ID |
| `PUT` | `/api/admin/transfers/{id}` | Actualizar estado |

### Items de Transferencia — `/api/admin/transfer-items`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/admin/transfer-items` | Agregar item |
| `GET` | `/api/admin/transfer-items/{id}` | Obtener por ID |
| `PUT` | `/api/admin/transfer-items/{id}` | Actualizar |
| `DELETE` | `/api/admin/transfer-items/{id}` | Eliminar |

### Alertas de Stock — `/api/admin/alerts`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `GET` | `/api/admin/alerts` | Listar alertas activas |
| `GET` | `/api/admin/alerts/{id}` | Obtener por ID |
| `GET` | `/api/admin/alerts/stock/{stock_id}` | Alertas por stock |

### Dashboard — `/api/admin/dashboard`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `GET` | `/api/admin/dashboard?expiringDays=30` | Valor del inventario, resumen por almacén y cantidad de alertas por tipo (`report:inventory:read` + `alert:read`) |

### Reportes de Inventario — `/api/admin/reports/inventory`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `GET` | `/api/admin/reports/inventory/valuation` | Valuacion de inventario |
| `GET` | `/api/admin/reports/inventory/rotation` | Reporte de rotacion |
| `GET` | `/api/admin/reports/inventory/movements` | Reporte de movimientos |
| `GET` | `/api/admin/reports/inventory/summary` | Resumen general |

---

## POS API

> **En desarrollo** — los endpoints listados a continuacion estan parcialmente implementados. Ver [pos-plan.md](pos-plan.md) para el plan completo.

### Ventas POS — `/api/pos/sales`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/api/pos/sales/{id}/confirm` | Confirmar venta (atomico con inventario) |
| `POST` | `/api/pos/sales/{id}/cancel` | Anular venta (atomico con inventario) |

> La creacion y gestion de items se realiza desde Admin (`/api/admin/sales`).

### Terminales POS — `/api/pos/terminals`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `GET` | `/api/pos/terminals` | Terminales activas de la sucursal de `X-Branch-Id` (obligatorio), para elegir la del POS |

### Productos POS — `/api/pos/products`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `GET` | `/api/pos/products` | Catalogo de productos para POS |
| `GET` | `/api/pos/products/{id}` | Obtener producto por ID |

### Clientes POS — `/api/pos/customers`

| Metodo | Ruta | Descripcion |
|---|---|---|
| `GET` | `/api/pos/customers` | Buscar clientes |
| `GET` | `/api/pos/customers/{id}` | Obtener cliente por ID |
| `GET` | `/api/pos/customers/tax-id/{tax_id}` | Buscar por RUC |

---

## Formato de Errores

Todos los errores siguen el mismo formato:

```json
{
  "errors": [
    {
      "code": "INVALID_PURCHASE_ORDER_STATUS",
      "message": "Cannot send a purchase order with status 'cancelled'",
      "detail": "current_status=cancelled, operation=send"
    }
  ],
  "meta": {"requestId": "550e8400-e29b-41d4-a716-446655440000", "timestamp": "2026-10-08T10:00:00Z"}
}
```

`field` aparece en los errores de validación (ruta del campo, p. ej. `body.code`) y `detail` cuando la excepción trae contexto adicional.

| `code` | HTTP | Origen |
|---|---|---|
| Códigos de estado por agregado (`INVALID_SALE_STATUS`, `INVALID_PURCHASE_ORDER_STATUS`, `INVALID_ADJUSTMENT_STATUS`, `INVALID_TRANSFER_STATUS`, `INVALID_SERIAL_STATUS`, `INVALID_REFUND_STATUS`…) y otras reglas de negocio (`INSUFFICIENT_STOCK`, `EXCEEDS_PENDING_QUANTITY`, `SALE_HAS_NO_ITEMS`…) | 400 | Subclases de `DomainError` en `<módulo>/domain/exceptions.py` |
| `*_ALREADY_EXISTS` (`PRODUCT_SKU_ALREADY_EXISTS`, `CUSTOMER_TAX_ID_ALREADY_EXISTS`, `LOCATION_CODE_ALREADY_EXISTS`…) | 409 | `AlreadyExistsError`; los repositorios traducen la violación de cada constraint de unicidad (`__unique_errors__`) |
| `ALREADY_EXISTS` | 409 | Violación de unicidad sin traducción específica |
| `RECORD_IN_USE` | 409 | Borrar un registro referenciado por otros (FK) |
| `REFERENCE_NOT_FOUND` | 422 | El cuerpo referencia un registro inexistente (FK) |
| `NOT_FOUND` | 404 | `NotFoundError` — recurso inexistente |
| `VALIDATION_ERROR` | 422 | Validación del request o `ValidationError` del dominio |
| `PERMISSION_DENIED` / `PASSWORD_CHANGE_REQUIRED` | 403 | Autorización |
| `INVALID_CREDENTIALS` / `INVALID_TOKEN` / `TOKEN_EXPIRED` | 401 | Autenticación |
| `INTERNAL_ERROR` | 500 | Excepción no controlada |
