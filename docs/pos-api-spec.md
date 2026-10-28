# Especificación Completa del Módulo POS — Faclab Core

## Base URL: `/api/pos`

Todos los endpoints usan JSON. Las respuestas siguen el formato `DataResponse`, `ListResponse`, o `PaginatedDataResponse`.

---

## 0. SUCURSAL Y TERMINAL (S2.6)

El POS opera en una terminal (`GET /terminals` lista las de la sucursal). Cada solicitud de operación
indica dónde corre con encabezados:

| Encabezado | Rutas | Si falta |
|------------|-------|----------|
| `X-Branch-Id` + `X-Terminal-Id` | Abrir turno, turno activo, crear venta, venta rápida, ventas aparcadas, crear devolución | `TERMINAL_REQUIRED` (400) o `BRANCH_REQUIRED` (400) |
| `X-Branch-Id` | Operaciones sobre una venta, un turno o una devolución existentes: ítems, pagos, descuento, precio, aparcar, reanudar, confirmar, cancelar, recibo, cerrar turno, movimientos y resumen de caja, procesar y cancelar devolución | `BRANCH_REQUIRED` (400) |

- La sucursal debe ser una a la que el usuario puede entrar (`BRANCH_ACCESS_DENIED`, 403).
- La terminal debe ser de esa sucursal (`POS_TERMINAL_OUTSIDE_BRANCH`, 400) y estar activa
  (`POS_TERMINAL_INACTIVE`, 409), igual que la sucursal (`BRANCH_INACTIVE`, 409). Un id mal formado
  responde `INVALID_TERMINAL_HEADER` (422).
- Una venta, un turno o una devolución de otra sucursal responde `NOT_FOUND` (404), igual que uno que
  no existe. Los anteriores a S2.6 no tienen sucursal y se pueden operar desde cualquiera.
- El historial y los reportes (`report:pos:read`) no piden encabezado: muestran las sucursales a las
  que el usuario puede entrar y aceptan los filtros `branchId` y `terminalId`. Un `branchId` ajeno
  responde `BRANCH_ACCESS_DENIED`.
- Sin los encabezados la solicitud se rechaza en todos los entornos (`TERMINAL_REQUIRED` o
  `BRANCH_REQUIRED`). faclab-web los envía desde S2.9: cada navegador queda vinculado a una caja de la
  sucursal (`GET /api/pos/terminals`). El respaldo local que elegía la primera terminal de la matriz
  (`POS_TERMINAL_FALLBACK`) se retiró en S2.9.

La terminal decide la ubicación del stock (su ubicación por defecto), el punto de emisión de la venta y
la caja (el turno abierto de la terminal).

## 0.1 IDEMPOTENCIA (S3.1)

Las operaciones que crean documentos o mueven dinero exigen el encabezado `Idempotency-Key`: un UUID
que el cliente genera **una vez por operación del usuario** (no por intento) y reenvía en cada reintento
de esa operación. Así, si la red falla después de que el core confirmó una venta, el reintento no la
duplica.

| Ruta | Efecto que protege |
|------|--------------------|
| `POST /sales` | Crea la venta (borrador) |
| `POST /sales/quick` | Venta completa: stock, número y pagos |
| `POST /sales/{id}/confirm` | Descuenta stock y numera |
| `POST /sales/{id}/payments` | Registra el pago |
| `POST /refunds` | Crea la devolución |
| `POST /refunds/{id}/process` | Devuelve dinero y stock |
| `POST /shifts/{id}/cash-movements` | Registra el movimiento de caja |

- **Primera solicitud**: reserva la clave y guarda la respuesta en la misma transacción que la operación.
- **Repetición con la misma clave y la misma solicitud** (método, ruta con sus ids y cuerpo JSON; el
  orden de los campos y los espacios no cuentan): devuelve la respuesta guardada, con el mismo status y
  el mismo cuerpo, y el encabezado `Idempotent-Replayed: true`. No se repite ningún efecto.
- **Simultáneas**: una solicitud cuya clave está reservada por otra que todavía corre espera a que
  termine (hasta 10 s) y devuelve su respuesta. Si la espera se vence: `IDEMPOTENCY_IN_PROGRESS` (409);
  reintentar más tarde con la misma clave.
- **Misma clave con otra solicitud**: `IDEMPOTENCY_KEY_REUSED` (422).
- **Errores**: no se guardan. Una operación que falla (4xx o 5xx) se revierte con su reserva, así que un
  reintento con la misma clave se ejecuta de nuevo (el intento fallido no dejó efectos).
- **Sin clave**: `IDEMPOTENCY_KEY_REQUIRED` (422); un valor que no es UUID: `INVALID_IDEMPOTENCY_KEY`
  (422). La bandera `IDEMPOTENCY_KEY_REQUIRED=false` (solo para revertir un despliegue) deja pasar las
  solicitudes sin clave.
- **Vigencia**: la clave es de la empresa y se purga a las 24 h (`IDEMPOTENCY_KEY_RETENTION_HOURS`,
  `make purge-idempotency-keys`).

faclab-web genera la clave por operación (`useIdempotencyKey`), la conserva hasta que la operación sale
bien y reintenta solo (hasta dos veces) tras un timeout, una caída de red, `IDEMPOTENCY_IN_PROGRESS` o
un 502/503/504.

---

## 1. TURNOS (Shifts)

### Entidad: Shift

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | int | ID auto-generado |
| cashierName | string | Cajero: el usuario autenticado que abre el turno (nombre completo o username). No se envía en el cuerpo |
| terminalId | int? | Terminal del turno (null solo en turnos anteriores a S2.6) |
| branchId | int? | Sucursal de la terminal |
| openedByUserId | int? | Usuario que abrió el turno |
| openedAt | datetime | Fecha/hora de apertura |
| closedAt | datetime? | Fecha/hora de cierre |
| openingBalance | decimal | Saldo inicial (≥0) |
| closingBalance | decimal? | Saldo de cierre declarado |
| expectedBalance | decimal? | Saldo esperado (calculado) |
| discrepancy | decimal? | closingBalance - expectedBalance |
| status | enum | `OPEN` \| `CLOSED` |
| notes | string? | Notas opcionales |
| closedBy | string? | Usuario autenticado que cerró el turno (no se envía en el cuerpo) |

### Regla clave

Cada terminal tiene como máximo **un turno OPEN** (lo garantiza un índice único parcial de la base:
una segunda apertura, incluso concurrente, responde `SHIFT_ALREADY_OPEN`). Dos terminales de la misma
sucursal pueden tener turnos abiertos a la vez. Las ventas y devoluciones van al turno abierto de su
terminal.

### Endpoints

**POST `/shifts/open`** — Abrir turno en la terminal de `X-Terminal-Id`

```json
// Request
{ "openingBalance": 100.00, "notes": "Turno matutino" }

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

**GET `/shifts/active`** — Turno abierto de la terminal (retorna `null` en `data` si no hay)

**GET `/shifts/{shiftId}`** — Turno por ID

**GET `/shifts?status=OPEN&branchId=1&terminalId=3&limit=20&offset=0`** — Listar turnos (paginado, del más reciente al más antiguo)

`GET /shifts` y `GET /shifts/{shiftId}` piden `report:pos:read` (no `pos:operate`): el historial de turnos también se consulta desde la administración. Solo muestran turnos de las sucursales a las que el usuario puede entrar.

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
| branchId | int? | Sucursal (de la terminal) |
| emissionPointId | int? | Punto de emisión de la terminal al crear la venta |
| terminalId | int? | Terminal |
| number | string? | Número correlativo por sucursal (`V-001-000123`), asignado al confirmar; null en borrador |
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
| createdBy | string? | Usuario autenticado que creó la venta (no se envía en el cuerpo) |
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
| amount | decimal | Aplicado a la venta: lo entregado menos el vuelto |
| amountTendered | decimal | Lo que entregó el cliente (>0), al centavo |
| change | decimal | Vuelto; solo en efectivo |
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
{ "customerId": 5, "isFinalConsumer": false, "notes": "..." }
// Si isFinalConsumer=true, customerId se ignora

// Response 201 — Sale en DRAFT vinculada al turno abierto de la terminal, con su sucursal,
// punto de emisión y terminal
```

**POST `/sales/quick`** — Venta rápida (atómica)

```json
// Request
{
  "customerId": null,
  "items": [
    { "productId": 1, "quantity": 2, "unitPrice": 10.50, "discount": 0 },
    { "productId": 2, "quantity": 1, "unitPrice": 8.00, "overrideReason": "Empaque dañado" },
    { "productId": 3, "quantity": 1 }
  ],
  "payments": [
    { "amount": 25.00, "paymentMethod": "CASH" }
  ],
  "discountType": "PERCENTAGE",
  "discountValue": 10,
  "notes": "Venta rápida"
}
// discountType/discountValue son opcionales y siguen las reglas de POST /sales/{saleId}/discount
```

Validaciones:

- Turno abierto en la terminal requerido
- Productos deben existir
- Stock suficiente para cada item en la ubicación de la terminal (lo de otras ubicaciones no cuenta)
- Descuento global válido (PERCENTAGE: 0-100; AMOUNT: ≥0)
- Cada `amount` es lo que entrega el cliente. Los pagos, en orden, toman lo que falta del total y el
  resto de uno en efectivo es el vuelto (`amountTendered`, `change`); deben cubrir el total
  (`INSUFFICIENT_PAYMENT`) y otro medio de pago no puede pasarse de lo que falta
  (`PAYMENT_EXCEEDS_BALANCE`). Se valida antes de tocar el stock
- `customerId=null` → `isFinalConsumer=true` automáticamente
- Un `unitPrice` distinto del precio del producto es un override: exige `overrideReason` (si falta, 400 `OVERRIDE_REASON_REQUIRED`) y queda registrado en el item (`priceOverride`, `overrideReason`), igual que con `POST /sales/{saleId}/items/{itemId}/price`

Response 201 — Sale CONFIRMED con su número, items y pagos incluidos.

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
- Los pagos cubren el total (`INSUFFICIENT_PAYMENT`): se vuelven a aplicar, en el orden en que se
  registraron, al total final, porque los ítems pueden haber cambiado después de cobrar; el vuelto de un
  pago en efectivo se recalcula y otro medio que ahora se pasa del total responde
  `PAYMENT_EXCEEDS_BALANCE`. Se valida antes de tocar el stock
- Stock suficiente para cada item en la ubicación de la terminal

Efectos:

- Status → CONFIRMED y `paymentStatus` → PAID, con el siguiente número de la sucursal (`number`)
- Crea Movement(OUT) por cada item en la ubicación de la terminal (`referenceType: "sale"`) → Stock decrementado
- Si algo falla no se consume número: el contador está en la misma transacción

**POST `/sales/{saleId}/cancel`** — Cancelar venta

```json
// Request (body opcional)
{ "reason": "Cliente desistió" }
// Si la venta estaba CONFIRMED: restaura inventario (Movement IN) en la ubicación de donde salió,
// aunque la terminal venda ahora desde otra. Conserva su número
```

- Una venta CONFIRMED cuya factura espera al SRI (su mensaje a facturación ya salió) no se cancela:
  `INVOICE_IN_PROGRESS`. Con la factura rechazada sí.
- Una venta INVOICED no se cancela: `CREDIT_NOTE_REQUIRED` (se anula con nota de crédito, S4.5).

**POST `/sales/{saleId}/park`** — Estacionar venta (pausar)

```json
// Request (body opcional)
{ "reason": "Cliente fue a buscar más productos" }
// Solo DRAFT. Marca parkedAt con timestamp actual
```

**POST `/sales/{saleId}/resume`** — Reanudar venta estacionada

**GET `/sales/parked`** — Listar las ventas estacionadas de la terminal

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
// amount: lo que entrega el cliente. Se aplica lo que falta pagar; el resto en efectivo es vuelto
// Response 201 — { ..., "amount": 34.50, "amountTendered": 50.00, "change": 15.50 }
```

- Una venta CANCELLED o INVOICED no recibe pagos: `SALE_NOT_PAYABLE`.
- Otro medio que no sea efectivo no puede pasarse de lo que falta, y un pago con la venta ya cubierta
  sobra: `PAYMENT_EXCEEDS_BALANCE`.

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
    "number": "V-001-000123",
    "branch": { "establishmentCode": "001", "name": "Matriz", "address": "Av. Amazonas" },
    "terminal": { "code": "CAJA-01", "name": "Caja 1" },
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
      { "method": "CASH", "amount": 24.15, "amountTendered": 25.00, "change": 0.85, "reference": null }
    ],
    "totalPaid": 24.15,
    "change": 0.85
  }
}
```

`cashier` es el usuario autenticado que hizo la venta (`createdBy`); en ventas anteriores, el cajero del
turno.

---

## 3. DEVOLUCIONES (Refunds)

### Entidad: Refund

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | int | ID |
| originalSaleId | int | Venta original |
| shiftId | int | Turno donde se procesa |
| branchId | int? | Sucursal (la de la venta) |
| terminalId | int? | Terminal donde se creó |
| number | string? | Número correlativo por sucursal (`D-001-000045`), asignado al procesar |
| refundDate | datetime? | Fecha de completado |
| subtotal | decimal | Base devuelta, neta del descuento global de la venta |
| tax | decimal | IVA devuelto |
| total | decimal | Total devuelto (`subtotal + tax`) |
| reason | string? | Razón |
| status | enum | `PENDING` → `COMPLETED` / `CANCELLED` |
| refundedBy | string? | Usuario autenticado que creó la devolución (no se envía en el cuerpo) |

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

La devolución reintegra lo que se cobró por esos items: aplica a su base e IVA el mismo factor de descuento global que tuvo la venta (`(subtotal - discount) / subtotal`) y redondea por código de IVA, igual que los totales de la venta (ver "Cálculos" en `sales-spec.md`). Devolver todos los items de una venta reintegra su total.

### Flujo de devolución

```
1. Crear devolución → POST /refunds  (seleccionar items y cantidades)
2. Procesar (pagar al cliente) → POST /refunds/{id}/process  (registrar pagos)
   → Inventario restaurado en la ubicación de la terminal (Movement IN) y número asignado
```

### Endpoints

**POST `/refunds`** — Crear devolución (PENDING). La venta debe estar `CONFIRMED` o `INVOICED`.

```json
// Request
{
  "originalSaleId": 1,
  "items": [
    { "saleItemId": 5, "quantity": 1 },
    { "saleItemId": 6, "quantity": 2 }
  ],
  "reason": "Producto defectuoso"
}
```

Validaciones:

- Venta original debe estar CONFIRMED
- La terminal debe ser de la sucursal de la venta (`REFUND_OUTSIDE_BRANCH`)
- Turno abierto en la terminal requerido
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

- Status → COMPLETED, con el siguiente número de devolución de la sucursal
- Crea Movement(IN) por cada item en la ubicación de la terminal de la devolución (`referenceType: "refund"`) → Stock incrementado
- Registra pagos de devolución

**POST `/refunds/{refundId}/cancel`** — Cancelar devolución (solo PENDING)

**GET `/refunds/{refundId}`** — Obtener devolución con items y pagos

**GET `/refunds?saleId=1&status=COMPLETED&branchId=1&terminalId=3&limit=20&offset=0`** — Listar (paginado, de la más reciente a la más antigua)

`GET /refunds` y `GET /refunds/{refundId}` piden `report:pos:read`, como el historial de turnos, y solo muestran devoluciones de las sucursales a las que el usuario puede entrar.

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
| performedBy | string? | Usuario autenticado que registró el movimiento (no se envía en el cuerpo) |
| createdAt | datetime | Fecha |

### Endpoints

**POST `/shifts/{shiftId}/cash-movements`** — Registrar movimiento

```json
// Request
{ "type": "OUT", "amount": 50.00, "reason": "Pago a proveedor" }

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

`cashSales` suma lo aplicado por los pagos en efectivo, sin el vuelto que se devolvió (S3.3): es lo que
quedó en la caja. Los reportes X, Z, diario y por medio de pago suman lo mismo.

---

## 5. REPORTES

X y Z son de un turno (de una sucursal a la que el usuario puede entrar; si no, `NOT_FOUND`). El diario
y el de método de pago cubren las sucursales del usuario y aceptan `branchId` y `terminalId`.

**GET `/reports/x-report?shiftId=1`** — Reporte X (turno en curso)

```json
{
  "data": {
    "shift": { "id": 1, "terminalId": 3, "branchId": 1, "cashierName": "Juan", "openedAt": "...", "status": "OPEN" },
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

**GET `/reports/daily?date=2026-03-14&branchId=1&terminalId=3`** — Resumen diario

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

**GET `/reports/by-payment-method?fromDate=2026-03-01&toDate=2026-03-14&branchId=1`** — Por método de pago

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
| `TERMINAL_REQUIRED` | 400 | Falta `X-Terminal-Id` |
| `BRANCH_REQUIRED` | 400 | Falta `X-Branch-Id` |
| `INVALID_TERMINAL_HEADER` | 422 | `X-Terminal-Id` no es un id |
| `BRANCH_ACCESS_DENIED` | 403 | El usuario no puede entrar a esa sucursal |
| `POS_TERMINAL_OUTSIDE_BRANCH` | 400 | La terminal es de otra sucursal |
| `POS_TERMINAL_INACTIVE` | 409 | La terminal está desactivada |
| `BRANCH_INACTIVE` | 409 | La sucursal está desactivada |
| `REFUND_OUTSIDE_BRANCH` | 400 | La venta se hizo en otra sucursal |
| `SHIFT_ALREADY_OPEN` | 400 | La terminal ya tiene un turno abierto |
| `SHIFT_ALREADY_CLOSED` | 400 | El turno ya está cerrado |
| `NO_OPEN_SHIFT` | 400 | No hay turno activo |
| `SALE_HAS_NO_ITEMS` | 400 | Venta sin items al confirmar |
| `INSUFFICIENT_PAYMENT` | 400 | Los pagos no cubren el total al confirmar (también en la venta rápida) |
| `PAYMENT_EXCEEDS_BALANCE` | 400 | Un pago que no es en efectivo se pasa de lo que falta, o la venta ya está cubierta |
| `SALE_NOT_PAYABLE` | 400 | Pago en una venta cancelada o facturada |
| `INVOICE_IN_PROGRESS` | 400 | Cancelar una venta cuya factura espera al SRI |
| `CREDIT_NOTE_REQUIRED` | 400 | Cancelar una venta facturada: se anula con nota de crédito |
| `INSUFFICIENT_STOCK` | 400 | La ubicación de la terminal no tiene disponible (sin lo reservado por transferencias) la suma de las líneas de un producto; `detail` dice `requested` y `available` |
| `INVALID_REFUND_STATUS` | 400 | Estado inválido para la operación |
| `EXCEEDS_ORIGINAL_QUANTITY` | 400 | Cantidad devuelta excede disponible |
| `SALE_NOT_CONFIRMED` | 400 | Venta no confirmada (para devolución) |
| `REFUND_ITEM_NOT_IN_SALE` | 400 | Item no pertenece a la venta |
| `INVALID_CASH_MOVEMENT_AMOUNT` | 400 | Monto debe ser > 0 |
| `SHIFT_NOT_OPEN_FOR_CASH_MOVEMENT` | 400 | Turno debe estar abierto |
| `IDEMPOTENCY_KEY_REQUIRED` | 422 | Falta `Idempotency-Key` en una operación que lo exige (§0.1) |
| `INVALID_IDEMPOTENCY_KEY` | 422 | `Idempotency-Key` no es un UUID |
| `IDEMPOTENCY_KEY_REUSED` | 422 | La clave ya se usó con otra solicitud |
| `IDEMPOTENCY_IN_PROGRESS` | 409 | Otra solicitud con la clave sigue en curso |

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

0. **Terminal**: El POS se vincula a una terminal de la sucursal (`GET /terminals` con `X-Branch-Id`) y envía `X-Branch-Id` y `X-Terminal-Id` en cada operación (§0).

1. **Turno obligatorio**: Antes de cualquier operación POS, verificar el turno de la terminal (`GET /shifts/active`). Si `data` es `null`, abrir uno.

2. **Consumidor final**: Si `isFinalConsumer=true`, no se necesita `customerId`. Si es `false`, el cliente es obligatorio.

3. **Impuestos**: Se calculan por item automáticamente (la tasa viene del producto, Ecuador usa 15% o 0%). El backend es la fuente de verdad; el frontend solo los muestra.

4. **Descuentos**: Dos niveles — por item (porcentaje en el item) y por venta (porcentaje o monto fijo). El descuento de venta se prorratea sobre la base imponible, así que el IVA se calcula después de ambos descuentos (ver "Cálculos" en `sales-spec.md`).

5. **Venta rápida vs normal**: Quick sale es ideal para ventas simples de 1 paso. La venta normal permite estacionar, agregar/quitar items, aplicar descuentos, etc.

6. **Estacionar ventas**: Solo en DRAFT. Útil cuando el cliente se va temporalmente. Listar con `GET /sales/parked`.

7. **Devoluciones parciales**: Se pueden devolver cantidades parciales de cada item. El sistema rastrea cuánto se ha devuelto previamente.

8. **Recibo**: Disponible después de confirmar. Incluye número, sucursal, terminal, cajero, desglose de impuestos, lo entregado y el vuelto de cada pago (guardados al cobrar), y toda la información para impresión.

9. **Cierre de caja**: El Z-Report da la reconciliación completa. La discrepancia (diferencia entre esperado y declarado) se registra automáticamente.

10. **Campos camelCase**: La API usa camelCase en JSON (ej: `cashierName`, `paymentMethod`, `taxCode`).

11. **Autoría desde el token**: `cashierName`, `closedBy`, `createdBy`, `refundedBy` y `performedBy` los pone el backend con el usuario autenticado (su nombre completo o, si no tiene, su username). No se envían en el cuerpo; si llegan, se ignoran.

12. **Idempotencia**: Las operaciones de §0.1 llevan `Idempotency-Key`, una por operación del usuario y la misma en cada reintento, hasta recibir una respuesta definitiva.

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
| POST | `/cash-movements` | Registrar movimiento (`Idempotency-Key`) |
| GET | `/cash-movements` | Listar movimientos |
| GET | `/cash-summary` | Resumen de caja |

### Sales (`/sales`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/` | Crear venta (`Idempotency-Key`) |
| POST | `/quick` | Venta rápida (`Idempotency-Key`) |
| GET | `/{id}` | Obtener venta |
| POST | `/{id}/items` | Agregar item |
| GET | `/{id}/items` | Listar items |
| PUT | `/{id}/items/{itemId}` | Actualizar item |
| DELETE | `/{id}/items/{itemId}` | Eliminar item |
| POST | `/{id}/confirm` | Confirmar (`Idempotency-Key`) |
| POST | `/{id}/cancel` | Cancelar |
| POST | `/{id}/park` | Estacionar |
| POST | `/{id}/resume` | Reanudar |
| POST | `/{id}/discount` | Aplicar descuento |
| POST | `/{id}/payments` | Registrar pago (`Idempotency-Key`) |
| GET | `/{id}/payments` | Listar pagos |
| PUT | `/{id}/items/{itemId}/price` | Sobrescribir precio |
| GET | `/{id}/receipt` | Generar recibo |
| GET | `/parked` | Ventas estacionadas |

### Refunds (`/refunds`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/` | Crear devolución (`Idempotency-Key`) |
| POST | `/{id}/process` | Procesar devolución (`Idempotency-Key`) |
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

### Terminals (`/terminals`)

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/` | Terminales activas de la sucursal de `X-Branch-Id` |

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
