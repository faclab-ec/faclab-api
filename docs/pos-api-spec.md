# Especificación Completa del Módulo POS — Faclab Core

## Base URL: `/api/pos`

Todos los endpoints usan JSON. Las respuestas siguen el formato `DataResponse`, `ListResponse`, o `PaginatedDataResponse`.

---

## 1. TURNOS (Shifts)

### Entidad: Shift

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | int | ID auto-generado |
| cashierName | string | Nombre del cajero (max 128) |
| openedAt | datetime | Fecha/hora de apertura |
| closedAt | datetime? | Fecha/hora de cierre |
| openingBalance | decimal | Saldo inicial (≥0) |
| closingBalance | decimal? | Saldo de cierre declarado |
| expectedBalance | decimal? | Saldo esperado (calculado) |
| discrepancy | decimal? | closingBalance - expectedBalance |
| status | enum | `OPEN` \| `CLOSED` |
| notes | string? | Notas opcionales |

### Regla clave

Solo puede existir **un turno OPEN** a la vez. Todas las operaciones POS (ventas, devoluciones, movimientos de caja) requieren un turno activo.

### Endpoints

**POST `/shifts/open`** — Abrir turno

```json
// Request
{ "cashierName": "Juan", "openingBalance": 100.00, "notes": "Turno matutino" }

// Response 201
{ "data": { "id": 1, "cashierName": "Juan", "openedAt": "...", "openingBalance": 100.00, "status": "OPEN", ... } }
```

**POST `/shifts/{shiftId}/close`** — Cerrar turno

```json
// Request
{ "closingBalance": 350.00, "notes": "Sin novedad" }

// Response — incluye expectedBalance y discrepancy calculados
{ "data": { "closingBalance": 350.00, "expectedBalance": 345.50, "discrepancy": 4.50, "status": "CLOSED" } }
```

Fórmula: `expectedBalance = openingBalance + cashSales - cashRefunds + cashIn - cashOut`

**GET `/shifts/active`** — Turno activo (retorna `null` en `data` si no hay)

**GET `/shifts/{shiftId}`** — Turno por ID

**GET `/shifts?status=OPEN&limit=20&offset=0`** — Listar turnos (paginado)

```json
{ "data": { "items": [...], "total": 50, "limit": 20, "offset": 0 } }
```

---

## 2. VENTAS POS

### Entidad: Sale

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | int | ID |
| customerId | int? | Cliente (null si consumidor final) |
| isFinalConsumer | bool | Sin factura (true = sin cliente) |
| shiftId | int | Turno asociado |
| status | enum | `DRAFT` → `CONFIRMED` → `INVOICED` / `CANCELLED` |
| saleDate | datetime? | Fecha de confirmación |
| subtotal | decimal | Suma de subtotales de items |
| tax | decimal | Suma de impuestos |
| discount | decimal | Descuento aplicado |
| discountType | string? | `PERCENTAGE` \| `AMOUNT` |
| discountValue | decimal | Valor del descuento |
| total | decimal | subtotal + tax - discount |
| paymentStatus | enum | `PENDING` \| `PARTIAL` \| `PAID` |
| notes | string? | Notas |
| createdBy | string? | Usuario que creó |
| parkedAt | datetime? | Fecha de estacionamiento |
| parkReason | string? | Razón de estacionamiento |
| createdAt | datetime | Fecha creación |

### Entidad: SaleItem

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | int | ID |
| saleId | int | Venta asociada |
| productId | int | Producto |
| quantity | int | Cantidad |
| unitPrice | decimal | Precio unitario |
| discount | decimal | Descuento % (0-100) |
| taxCode | string | Código semántico de IVA (ej: VAT_15) |
| taxAmount | decimal | Monto de impuesto calculado |
| subtotal | decimal | (unitPrice × quantity) × (1 - discount/100) |
| priceOverride | decimal? | Precio sobrescrito |
| overrideReason | string? | Razón de sobrescritura |

### Entidad: Payment

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | int | ID |
| saleId | int | Venta |
| amount | decimal | Monto (>0) |
| paymentMethod | enum | `CASH` \| `CREDIT_CARD` \| `DEBIT_CARD` \| `TRANSFER` \| `OTHER` |
| paymentDate | datetime | Fecha auto-generada |
| reference | string? | Referencia de pago |
| notes | string? | Notas |

### Flujo de venta normal

```
1. Crear venta (DRAFT) → POST /sales
2. Agregar items → POST /sales/{id}/items  (repetir)
3. Aplicar descuento (opcional) → POST /sales/{id}/discount
4. Registrar pagos → POST /sales/{id}/payments  (repetir)
5. Confirmar → POST /sales/{id}/confirm
```

### Flujo de venta rápida (atómico, un solo request)

```
POST /sales/quick  →  Crea + Items + Confirma + Pagos en una sola transacción
```

### Endpoints

**POST `/sales`** — Crear venta (DRAFT)

```json
// Request
{ "customerId": 5, "isFinalConsumer": false, "notes": "...", "createdBy": "cajero1" }
// Si isFinalConsumer=true, customerId se ignora

// Response 201 — Sale en DRAFT vinculada al turno activo
```

**POST `/sales/quick`** — Venta rápida (atómica)

```json
// Request
{
  "customerId": null,
  "items": [
    { "productId": 1, "quantity": 2, "unitPrice": 10.50, "discount": 0 },
    { "productId": 3, "quantity": 1 }
  ],
  "payments": [
    { "amount": 25.00, "paymentMethod": "CASH" }
  ],
  "discountType": "PERCENTAGE",
  "discountValue": 10,
  "notes": "Venta rápida",
  "createdBy": "cajero1"
}
// discountType/discountValue son opcionales y siguen las reglas de POST /sales/{saleId}/discount
```

Validaciones:

- Turno activo requerido
- Productos deben existir
- Stock suficiente para cada item
- Descuento global válido (PERCENTAGE: 0-100; AMOUNT: ≥0)
- Total de pagos ≥ total de venta, comparados al centavo
- `customerId=null` → `isFinalConsumer=true` automáticamente

Response 201 — Sale CONFIRMED con items y pagos incluidos.

**GET `/sales/{saleId}`** — Obtener venta

**POST `/sales/{saleId}/items`** — Agregar item

```json
// Request
{ "productId": 1, "quantity": 3, "unitPrice": 10.50, "discount": 0 }
// unitPrice es obligatorio, discount es opcional (default 0, rango 0-100)
// Response 201
```

**GET `/sales/{saleId}/items`** — Listar items

**PUT `/sales/{saleId}/items/{itemId}`** — Actualizar item (quantity y/o discount)

```json
// Request — ambos campos son opcionales, enviar solo los que se quieren cambiar
{ "quantity": 5, "discount": 10 }
```

**DELETE `/sales/{saleId}/items/{itemId}`** — Eliminar item

**POST `/sales/{saleId}/confirm`** — Confirmar venta

Validaciones:

- Venta debe tener items
- Turno asociado debe estar OPEN
- Stock suficiente para cada item

Efectos:

- Status → CONFIRMED
- Crea Movement(OUT) por cada item → Stock decrementado

**POST `/sales/{saleId}/cancel`** — Cancelar venta

```json
// Request (body opcional)
{ "reason": "Cliente desistió" }
// Si la venta estaba CONFIRMED: restaura inventario (Movement IN)
```

**POST `/sales/{saleId}/park`** — Estacionar venta (pausar)

```json
// Request (body opcional)
{ "reason": "Cliente fue a buscar más productos" }
// Solo DRAFT. Marca parkedAt con timestamp actual
```

**POST `/sales/{saleId}/resume`** — Reanudar venta estacionada

**GET `/sales/parked`** — Listar ventas estacionadas

**POST `/sales/{saleId}/discount`** — Aplicar descuento a nivel de venta

```json
{ "discountType": "PERCENTAGE", "discountValue": 10 }
// o
{ "discountType": "AMOUNT", "discountValue": 5.00 }
// Solo DRAFT. PERCENTAGE: 0-100. AMOUNT: ≥0
```

**POST `/sales/{saleId}/payments`** — Registrar pago

```json
{ "amount": 50.00, "paymentMethod": "CASH", "reference": null, "notes": null }
// Response 201
```

**GET `/sales/{saleId}/payments`** — Listar pagos

**PUT `/sales/{saleId}/items/{itemId}/price`** — Sobrescribir precio

```json
{ "newPrice": 8.50, "reason": "Descuento especial cliente frecuente" }
// Solo DRAFT. newPrice > 0. Recalcula impuestos y totales
```

**GET `/sales/{saleId}/receipt`** — Generar recibo

```json
// Response
{
  "data": {
    "saleId": 1,
    "saleDate": "2026-03-14T10:30:00",
    "status": "CONFIRMED",
    "cashier": "Juan",
    "customer": { "name": "...", "taxId": "...", "address": "..." },
    "isFinalConsumer": false,
    "items": [
      {
        "productName": "Producto X",
        "quantity": 2,
        "unitPrice": 10.50,
        "discount": 0,
        "discountAmount": 0,
        "taxCode": "VAT_15",
        "taxAmount": 3.15,
        "subtotal": 21.00,
        "priceOverride": null,
        "overrideReason": null
      }
    ],
    "taxBreakdown": [
      { "taxCode": "VAT_15", "taxRate": 15, "taxableBase": 21.00, "taxAmount": 3.15 }
    ],
    "subtotal": 21.00,
    "discount": 0,
    "discountType": null,
    "discountValue": 0,
    "tax": 3.15,
    "total": 24.15,
    "payments": [
      { "method": "CASH", "amount": 25.00, "reference": null }
    ],
    "totalPaid": 25.00,
    "change": 0.85
  }
}
```

---

## 3. DEVOLUCIONES (Refunds)

### Entidad: Refund

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | int | ID |
| originalSaleId | int | Venta original |
| shiftId | int | Turno donde se procesa |
| refundDate | datetime? | Fecha de completado |
| subtotal | decimal | Subtotal devuelto |
| tax | decimal | Impuesto devuelto |
| total | decimal | Total devuelto |
| reason | string? | Razón |
| status | enum | `PENDING` → `COMPLETED` / `CANCELLED` |
| refundedBy | string? | Quién procesó |

### Entidad: RefundItem

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | int | ID |
| refundId | int | Devolución |
| originalSaleItemId | int | Item original de la venta |
| productId | int | Producto |
| quantity | int | Cantidad devuelta |
| unitPrice | decimal | Precio (copiado del original) |
| discount | decimal | Descuento % (copiado) |
| taxCode | string | Código de IVA (copiado del original) |
| taxAmount | decimal | Impuesto calculado |
| subtotal | decimal | Calculado |

### Entidad: RefundPayment

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | int | ID |
| refundId | int | Devolución |
| amount | decimal | Monto (>0) |
| paymentMethod | enum | `CASH` \| `CREDIT_CARD` \| `DEBIT_CARD` \| `TRANSFER` \| `OTHER` |
| reference | string? | Referencia |

### Flujo de devolución

```
1. Crear devolución → POST /refunds  (seleccionar items y cantidades)
2. Procesar (pagar al cliente) → POST /refunds/{id}/process  (registrar pagos)
   → Inventario restaurado automáticamente (Movement IN)
```

### Endpoints

**POST `/refunds`** — Crear devolución (PENDING)

```json
// Request
{
  "originalSaleId": 1,
  "items": [
    { "saleItemId": 5, "quantity": 1 },
    { "saleItemId": 6, "quantity": 2 }
  ],
  "reason": "Producto defectuoso",
  "refundedBy": "cajero1"
}
```

Validaciones:

- Venta original debe estar CONFIRMED
- Turno activo requerido
- Cada item debe pertenecer a la venta
- Cantidad no puede exceder la disponible (original - ya devuelto)

Response 201 — Refund con items y subtotales.

**POST `/refunds/{refundId}/process`** — Procesar devolución

```json
// Request
{
  "payments": [
    { "amount": 15.00, "paymentMethod": "CASH", "reference": null }
  ]
}
```

Validaciones: total pagos ≥ total devolución.

Efectos:

- Status → COMPLETED
- Crea Movement(IN) por cada item → Stock incrementado
- Registra pagos de devolución

**POST `/refunds/{refundId}/cancel`** — Cancelar devolución (solo PENDING)

**GET `/refunds/{refundId}`** — Obtener devolución con items y pagos

**GET `/refunds?saleId=1&status=COMPLETED&limit=20&offset=0`** — Listar (paginado)

---

## 4. MOVIMIENTOS DE CAJA (Cash Movements)

### Entidad: CashMovement

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | int | ID |
| shiftId | int | Turno |
| type | enum | `IN` \| `OUT` |
| amount | decimal | Monto (>0) |
| reason | string? | Razón |
| performedBy | string? | Quién lo hizo |
| createdAt | datetime | Fecha |

### Endpoints

**POST `/shifts/{shiftId}/cash-movements`** — Registrar movimiento

```json
// Request
{ "type": "OUT", "amount": 50.00, "reason": "Pago a proveedor", "performedBy": "cajero1" }

// Validaciones: amount > 0, turno debe estar OPEN
// Response 201
```

**GET `/shifts/{shiftId}/cash-movements?limit=100&offset=0`** — Listar (paginado)

**GET `/shifts/{shiftId}/cash-summary`** — Resumen de caja

```json
// Response
{
  "data": {
    "shiftId": 1,
    "openingBalance": 100.00,
    "cashSales": 500.00,
    "cashRefunds": 30.00,
    "cashIn": 200.00,
    "cashOut": 50.00,
    "expectedBalance": 720.00
  }
}
```

Fórmula: `expectedBalance = openingBalance + cashSales - cashRefunds + cashIn - cashOut`

---

## 5. REPORTES

**GET `/reports/x-report?shiftId=1`** — Reporte X (turno en curso)

```json
{
  "data": {
    "shift": { "id": 1, "cashierName": "Juan", "openedAt": "...", "status": "OPEN" },
    "salesSummary": { "count": 15, "subtotal": 1200, "tax": 180, "discount": 50, "total": 1330 },
    "paymentsByMethod": [
      { "paymentMethod": "CASH", "count": 10, "total": 800 },
      { "paymentMethod": "CREDIT_CARD", "count": 5, "total": 530 }
    ],
    "itemsSold": [
      { "productName": "Producto X", "sku": "SKU001", "quantity": 20, "total": 500 }
    ]
  }
}
```

**GET `/reports/z-report?shiftId=1`** — Reporte Z (cierre de turno)

```json
// Incluye todo del X-Report más:
{
  "refundSummary": { "count": 2, "total": 45.00 },
  "cashReconciliation": {
    "openingBalance": 100,
    "cashSales": 500,
    "cashRefunds": 30,
    "cashIn": 200,
    "cashOut": 50,
    "expectedBalance": 720,
    "closingBalance": 715,
    "discrepancy": -5
  }
}
```

**GET `/reports/daily?date=2026-03-14`** — Resumen diario

```json
{
  "data": {
    "date": "2026-03-14",
    "totalSales": 45,
    "totalAmount": 5200.00,
    "paymentsByMethod": [
      { "paymentMethod": "CASH", "count": 30, "total": 3500 }
    ],
    "topProducts": [
      { "productName": "...", "sku": "...", "quantity": 50, "total": 1200 }
    ],
    "refundSummary": { "count": 3, "total": 120 }
  }
}
```

**GET `/reports/by-payment-method?fromDate=2026-03-01&toDate=2026-03-14`** — Por método de pago

```json
{ "data": [{ "paymentMethod": "CASH", "salesCount": 100, "totalAmount": 5000 }] }
```

---

## 6. PRODUCTOS Y CLIENTES (endpoints POS simplificados)

### Productos

**GET `/products`** — Listar todos

**GET `/products/search?term=coca&limit=20`** — Buscar por SKU, código de barras, o nombre

**GET `/products/{id}`** — Obtener por ID

### Clientes

**POST `/customers`** — Creación rápida

```json
{ "name": "María López", "taxId": "1712345678001", "taxType": 1 }
// taxType: 1=RUC, 2=NATIONAL_ID, 3=PASSPORT, 4=FOREIGN_ID
```

**GET `/customers`** — Listar todos

**GET `/customers/search/by-tax-id?taxId=1712345678001`** — Buscar por RUC/cédula

**GET `/customers/{id}`** — Obtener por ID

---

## 7. CÓDIGOS DE ERROR

| Código | HTTP | Descripción |
|--------|------|-------------|
| `SHIFT_ALREADY_OPEN` | 400 | Ya existe un turno abierto |
| `SHIFT_ALREADY_CLOSED` | 400 | El turno ya está cerrado |
| `NO_OPEN_SHIFT` | 400 | No hay turno activo |
| `SALE_HAS_NO_ITEMS` | 400 | Venta sin items al confirmar |
| `INSUFFICIENT_STOCK` | 400 | Stock insuficiente |
| `INVALID_REFUND_STATUS` | 400 | Estado inválido para la operación |
| `EXCEEDS_ORIGINAL_QUANTITY` | 400 | Cantidad devuelta excede disponible |
| `SALE_NOT_CONFIRMED` | 400 | Venta no confirmada (para devolución) |
| `REFUND_ITEM_NOT_IN_SALE` | 400 | Item no pertenece a la venta |
| `INVALID_CASH_MOVEMENT_AMOUNT` | 400 | Monto debe ser > 0 |
| `SHIFT_NOT_OPEN_FOR_CASH_MOVEMENT` | 400 | Turno debe estar abierto |

Formato de error estándar:

```json
{
  "errorCode": "NO_OPEN_SHIFT",
  "message": "No open shift found",
  "timestamp": "2026-03-14T10:30:00",
  "requestId": "uuid",
  "detail": null
}
```

---

## 8. REGLAS DE NEGOCIO CLAVE PARA FRONTEND

1. **Turno obligatorio**: Antes de cualquier operación POS, verificar turno activo (`GET /shifts/active`). Si `data` es `null`, abrir uno.

2. **Consumidor final**: Si `isFinalConsumer=true`, no se necesita `customerId`. Si es `false`, el cliente es obligatorio.

3. **Impuestos**: Se calculan por item automáticamente (la tasa viene del producto, Ecuador usa 15% o 0%). El backend es la fuente de verdad; el frontend solo los muestra.

4. **Descuentos**: Dos niveles — por item (porcentaje en el item) y por venta (porcentaje o monto fijo). El descuento de venta se prorratea sobre la base imponible, así que el IVA se calcula después de ambos descuentos (ver "Cálculos" en `sales-spec.md`).

5. **Venta rápida vs normal**: Quick sale es ideal para ventas simples de 1 paso. La venta normal permite estacionar, agregar/quitar items, aplicar descuentos, etc.

6. **Estacionar ventas**: Solo en DRAFT. Útil cuando el cliente se va temporalmente. Listar con `GET /sales/parked`.

7. **Devoluciones parciales**: Se pueden devolver cantidades parciales de cada item. El sistema rastrea cuánto se ha devuelto previamente.

8. **Recibo**: Disponible después de confirmar. Incluye desglose de impuestos, cambio calculado, y toda la información para impresión.

9. **Cierre de caja**: El Z-Report da la reconciliación completa. La discrepancia (diferencia entre esperado y declarado) se registra automáticamente.

10. **Campos camelCase**: La API usa camelCase en JSON (ej: `cashierName`, `paymentMethod`, `taxCode`).

---

## 9. RESUMEN DE ENDPOINTS

### Shifts (`/shifts`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/open` | Abrir turno |
| POST | `/{id}/close` | Cerrar turno |
| GET | `/active` | Turno activo |
| GET | `/{id}` | Obtener turno |
| GET | `/` | Listar turnos |

### Cash (`/shifts/{id}`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/cash-movements` | Registrar movimiento |
| GET | `/cash-movements` | Listar movimientos |
| GET | `/cash-summary` | Resumen de caja |

### Sales (`/sales`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/` | Crear venta |
| POST | `/quick` | Venta rápida |
| GET | `/{id}` | Obtener venta |
| POST | `/{id}/items` | Agregar item |
| GET | `/{id}/items` | Listar items |
| PUT | `/{id}/items/{itemId}` | Actualizar item |
| DELETE | `/{id}/items/{itemId}` | Eliminar item |
| POST | `/{id}/confirm` | Confirmar |
| POST | `/{id}/cancel` | Cancelar |
| POST | `/{id}/park` | Estacionar |
| POST | `/{id}/resume` | Reanudar |
| POST | `/{id}/discount` | Aplicar descuento |
| POST | `/{id}/payments` | Registrar pago |
| GET | `/{id}/payments` | Listar pagos |
| PUT | `/{id}/items/{itemId}/price` | Sobrescribir precio |
| GET | `/{id}/receipt` | Generar recibo |
| GET | `/parked` | Ventas estacionadas |

### Refunds (`/refunds`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/` | Crear devolución |
| POST | `/{id}/process` | Procesar devolución |
| POST | `/{id}/cancel` | Cancelar devolución |
| GET | `/{id}` | Obtener devolución |
| GET | `/` | Listar devoluciones |

### Reports (`/reports`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/x-report` | Reporte X |
| GET | `/z-report` | Reporte Z |
| GET | `/daily` | Resumen diario |
| GET | `/by-payment-method` | Por método de pago |

### Products (`/products`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/` | Listar productos |
| GET | `/search` | Buscar productos |
| GET | `/{id}` | Obtener producto |

### Customers (`/customers`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/` | Crear cliente rápido |
| GET | `/` | Listar clientes |
| GET | `/search/by-tax-id` | Buscar por RUC/cédula |
| GET | `/{id}` | Obtener cliente |
