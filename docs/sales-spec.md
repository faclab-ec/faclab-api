# Sales Module — API Specification (Admin, solo lectura)

Specification del módulo de ventas para implementación frontend. Solo endpoints de consulta (Admin).

---

## 1. Enums

### SaleStatus

| Valor        | Descripción                  |
|--------------|------------------------------|
| `DRAFT`      | Borrador, editable           |
| `CONFIRMED`  | Confirmada, stock descontado |
| `INVOICED`   | Facturada: el SRI autorizó su factura (lo informa faclab-invoicing) |
| `CANCELLED`  | Cancelada                    |

### PaymentStatus

| Valor     | Descripción                   |
|-----------|-------------------------------|
| `PENDING` | Sin pagos registrados         |
| `PARTIAL` | Pago parcial recibido         |
| `PAID`    | Pagado completamente          |

### PaymentMethod

`CASH` | `CREDIT_CARD` | `DEBIT_CARD` | `TRANSFER` | `OTHER`

---

## 2. Endpoints

Base URL: `/api/admin/sales`

### 2.1 Listar ventas

```
GET /api/admin/sales?customerId=1&status=DRAFT&limit=20&offset=0
```

| Query Param  | Tipo   | Default | Validación    |
|-------------|--------|---------|---------------|
| customerId  | int    | null    | >= 1          |
| status      | string | null    | SaleStatus    |
| limit       | int    | 100     | 1–1000        |
| offset      | int    | 0       | >= 0          |

**Response** `200`:

```json
{
  "data": [
    {
      "id": 1,
      "customerId": 1,
      "shiftId": 4,
      "branchId": 1,
      "emissionPointId": 1,
      "terminalId": 3,
      "number": "V-001-000123",
      "status": "CONFIRMED",
      "saleDate": "2026-03-08T10:00:00",
      "subtotal": 269.91,
      "tax": 0,
      "discount": 0,
      "total": 269.91,
      "paymentStatus": "PAID",
      "notes": null,
      "createdBy": "admin",
      "createdAt": "2026-03-08T09:50:00",
      "updatedAt": "2026-03-08T10:00:00"
    }
  ],
  "meta": {
    "requestId": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-03-08T10:05:00",
    "pagination": { "total": 50, "limit": 20, "offset": 0 }
  }
}
```

---

### 2.2 Obtener venta por ID

```
GET /api/admin/sales/{sale_id}
```

**Response** `200`:

```json
{
  "data": {
    "id": 1,
    "customerId": 1,
    "shiftId": 4,
    "branchId": 1,
    "emissionPointId": 1,
    "terminalId": 3,
    "number": "V-001-000123",
    "status": "CONFIRMED",
    "saleDate": "2026-03-08T10:00:00",
    "subtotal": 269.91,
    "tax": 0,
    "discount": 0,
    "total": 269.91,
    "paymentStatus": "PAID",
    "notes": null,
    "createdBy": "admin",
    "createdAt": "2026-03-08T09:50:00",
    "updatedAt": "2026-03-08T10:00:00"
  },
  "meta": {
    "requestId": "uuid",
    "timestamp": "2026-03-08T10:05:00"
  }
}
```

Las ventas las crea el POS en una terminal (S2.6): `branchId`, `emissionPointId` y `terminalId` son los
de la terminal, y `number` es el correlativo de la sucursal (`V-` + código de establecimiento + seis
dígitos), asignado al confirmar y que se conserva aunque la venta se cancele. Son `null` en los
borradores (`number`) y en las ventas anteriores a S2.6 o del seed.

**Error** `404`:

```json
{
  "errors": [{ "code": "NOT_FOUND", "message": "Sale not found", "field": null }],
  "meta": { "requestId": "uuid", "timestamp": "..." }
}
```

---

### 2.3 Listar items de una venta

```
GET /api/admin/sales/{sale_id}/items
```

**Response** `200`:

```json
{
  "data": [
    {
      "id": 1,
      "saleId": 1,
      "productId": 5,
      "quantity": 3,
      "unitPrice": 29.99,
      "discount": 10,
      "subtotal": 80.97
    },
    {
      "id": 2,
      "saleId": 1,
      "productId": 8,
      "quantity": 2,
      "unitPrice": 49.99,
      "discount": 0,
      "subtotal": 99.98
    }
  ],
  "meta": { "requestId": "uuid", "timestamp": "..." }
}
```

---

### 2.4 Listar pagos de una venta

```
GET /api/admin/sales/{sale_id}/payments
```

**Response** `200`:

```json
{
  "data": [
    {
      "id": 1,
      "saleId": 1,
      "amount": 150.00,
      "paymentMethod": "CASH",
      "paymentDate": "2026-03-08T10:00:00",
      "reference": "REF-001",
      "notes": null,
      "createdAt": "2026-03-08T10:00:00"
    },
    {
      "id": 2,
      "saleId": 1,
      "amount": 119.91,
      "paymentMethod": "CREDIT_CARD",
      "paymentDate": "2026-03-08T10:02:00",
      "reference": null,
      "notes": "Pago restante",
      "createdAt": "2026-03-08T10:02:00"
    }
  ],
  "meta": { "requestId": "uuid", "timestamp": "..." }
}
```

---

### 2.5 Reenviar una venta a facturación

```
POST /api/admin/sales/{sale_id}/request-invoice
```

Permiso: `sale:write`. Vuelve a publicar la venta en `sales.confirmed` (mismo mensaje, `event_id` nuevo) para cuando su factura nunca llegó a faclab-invoicing o el SRI la rechazó y ya se corrigieron los datos (por ejemplo, la cédula del cliente). No mueve inventario.

faclab-invoicing ignora el reenvío si la venta ya tiene una factura que no está rechazada (pendiente, en proceso o autorizada), así que reenviar de más no duplica facturas. Las facturas que esperan la configuración fiscal o un reintento del SRI no necesitan reenvío: se reanudan solas en faclab-invoicing.

Solo ventas `CONFIRMED`; en otro estado responde `400 INVALID_SALE_STATUS`. Si `KAFKA_ENABLED` está apagado responde `400 INVOICING_DISABLED`.

**Response** `202`: la venta (mismo formato que 2.2).

---

## 3. Formato de respuestas

### Envelope estándar

Todas las respuestas usan un envelope con `data` y `meta`:

```typescript
// Respuesta de un solo recurso
interface DataResponse<T> {
  data: T;
  meta: { requestId: string; timestamp: string };
}

// Respuesta de lista
interface ListResponse<T> {
  data: T[];
  meta: { requestId: string; timestamp: string };
}

// Respuesta paginada
interface PaginatedDataResponse<T> {
  data: T[];
  meta: {
    requestId: string;
    timestamp: string;
    pagination: { total: number; limit: number; offset: number };
  };
}

// Respuesta de error
interface ErrorResponse {
  errors: Array<{ code: string; message: string; field: string | null }>;
  meta: { requestId: string; timestamp: string };
}
```

### Convenciones

- Todos los campos JSON usan **camelCase**.
- Los campos `Decimal` se serializan como **números JSON** (no strings).
- Los campos `datetime` se serializan como strings ISO 8601.

---

## 4. Tipos TypeScript (referencia frontend)

```typescript
// Enums
type SaleStatus = "DRAFT" | "CONFIRMED" | "INVOICED" | "CANCELLED";
type PaymentStatus = "PENDING" | "PARTIAL" | "PAID";
type PaymentMethod = "CASH" | "CREDIT_CARD" | "DEBIT_CARD" | "TRANSFER" | "OTHER";

// Entidades
interface Sale {
  id: number;
  customerId: number;
  shiftId: number | null;
  branchId: number | null;
  emissionPointId: number | null;
  terminalId: number | null;
  number: string | null;
  status: SaleStatus;
  saleDate: string | null;
  subtotal: number;
  tax: number;
  discount: number;
  total: number;
  paymentStatus: PaymentStatus;
  notes: string | null;
  createdBy: string | null;
  createdAt: string;
  updatedAt: string | null;
}

interface SaleItem {
  id: number;
  saleId: number;
  productId: number;
  productName: string | null;
  productSku: string | null;
  quantity: number;
  unitPrice: number;
  discount: number;
  subtotal: number;
}

interface Payment {
  id: number;
  saleId: number;
  amount: number;
  paymentMethod: PaymentMethod;
  paymentDate: string | null;
  reference: string | null;
  notes: string | null;
  createdAt: string;
}

// Query params (para listar ventas)
interface SaleQueryParams {
  customerId?: number;
  status?: SaleStatus;
  limit?: number;  // default: 100, max: 1000
  offset?: number; // default: 0
}
```

---

## 5. Manejo de errores

| Código            | HTTP | Descripción                        |
|-------------------|------|------------------------------------|
| `NOT_FOUND`       | 404  | Venta no encontrada                |
| `VALIDATION_ERROR`| 422  | Query params inválidos             |
| `INVALID_SALE_STATUS` | 400 | Reenvío a facturación de una venta que no está `CONFIRMED` |
| `INVOICING_DISABLED`  | 400 | Reenvío a facturación con `KAFKA_ENABLED` apagado |

### Estructura de error

```json
{
  "errors": [
    {
      "code": "NOT_FOUND",
      "message": "Sale not found",
      "field": null
    }
  ],
  "meta": {
    "requestId": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-03-08T10:00:00"
  }
}
```

---

## 6. Cálculos (referencia)

Estos cálculos los hace el backend. Se documentan para que el frontend pueda mostrar o verificar los valores.

### Subtotal de item

```
item.subtotal = (unitPrice × quantity) × (1 - discount / 100)
```

Ejemplo: unitPrice=100, quantity=2, discount=10 → `(100 × 2) × (1 - 0.10) = 180`

### Totales de venta

```
item.taxAmount = item.subtotal × tasa del taxCode / 100          (precisión completa)

sale.subtotal = redondear(Σ item.subtotal)
sale.discount = redondear(subtotal × discountValue / 100)        (discountType = PERCENTAGE)
              = min(redondear(discountValue), subtotal)          (discountType = AMOUNT)
factor        = (subtotal - discount) / subtotal
sale.tax      = Σ por taxCode de redondear(Σ item.taxAmount del código × factor)
sale.total    = subtotal - discount + tax
```

`redondear` es a centavos con la mitad hacia arriba (`round_money` en `src/shared/domain/money.py`). Los items guardan sus montos con precisión completa; solo se redondean los totales de la venta, así que `total` es exactamente `subtotal - discount + tax`.

El descuento global se prorratea sobre la base imponible de cada item, porque el IVA se calcula sobre el precio menos los descuentos que constan en la factura (art. 59 de la LORTI). `item.taxAmount` guarda el IVA del item antes del descuento global. El IVA se redondea por código (como `totalConImpuestos` en la factura electrónica) y el desglose del recibo usa los mismos montos, de modo que suma exactamente `sale.tax`.

Ejemplo: un item de 100 con IVA 15% y descuento global del 10% → descuento 10, IVA 15% de 90 = 13,50, total 103,50.

Ejemplo de redondeo: 3 × 0,15 con IVA 15% → subtotal 0,45, IVA 0,0675 → 0,07, total 0,52.

El descuento global hoy se aplica desde el POS (`POST /api/pos/sales/{id}/discount` o `discountType`/`discountValue` en `POST /api/pos/sales/quick`).

### Payment status

```
total_paid = Σ payment.amount
if total_paid == 0:        PENDING
elif total_paid < total:   PARTIAL
else:                      PAID
```

`total_paid` y `total` se comparan redondeados al centavo.
