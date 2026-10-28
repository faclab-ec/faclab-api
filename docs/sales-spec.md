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
borradores (`number`) y en las ventas anteriores a S2.6. Desde S2.8 el seed crea sus ventas en la
terminal de la matriz, con sucursal, punto de emisión y número.

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
      "amountTendered": 160.00,
      "change": 10.00,
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
      "amountTendered": 119.91,
      "change": 0,
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

`amount` es lo aplicado a la venta, `amountTendered` lo que entregó el cliente y `change` el vuelto
(solo en efectivo): `amountTendered = amount + change` (ver «Pagos» en la sección de reglas).

---

### 2.5 Reenviar una venta a facturación

```
POST /api/admin/sales/{sale_id}/request-invoice
```

Permiso: `sale:write`. Vuelve a publicar la venta en `sales.confirmed` (mismo mensaje, `event_id` nuevo) para cuando su factura nunca llegó a faclab-invoicing o el SRI la rechazó y ya se corrigieron los datos (por ejemplo, la cédula del cliente). No mueve inventario.

faclab-invoicing ignora el reenvío si la venta ya tiene una factura que no está rechazada (pendiente, en proceso o autorizada), así que reenviar de más no duplica facturas. Las facturas que esperan la configuración fiscal o un reintento del SRI no necesitan reenvío: se reanudan solas en faclab-invoicing.

El mensaje dice quién emite y desde dónde (`sales.confirmed` v2): la empresa, su RUC, el establecimiento y la dirección de la sucursal de la venta y su punto de emisión. faclab-invoicing factura con el perfil fiscal, el certificado y el secuencial de esa empresa, establecimiento y punto de emisión.

Solo ventas `CONFIRMED`; en otro estado responde `400 INVALID_SALE_STATUS`. Una venta sin punto de emisión (anterior a S2.6) no se puede facturar: `400 SALE_WITHOUT_EMISSION_POINT`. Si `KAFKA_ENABLED` está apagado responde `400 INVOICING_DISABLED`. Sus pagos se vuelven a aplicar al total, así que los `pagos` de la factura suman el total; una venta confirmada antes de S3.3 sin cubrirlo responde `400 INSUFFICIENT_PAYMENT`. Con el mensaje en el outbox, la factura queda pendiente (`INVOICE_IN_PROGRESS` al cancelar).

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
type InvoiceStatus = "PENDING" | "AUTHORIZED" | "REJECTED";
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
  invoiceStatus: InvoiceStatus | null; // null: nunca se envió a facturación
  invoiceId: string | null; // última factura con resultado en faclab-invoicing
  invoiceRejectionReason: string | null; // mensajes del SRI, mientras está REJECTED
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
  amount: number;          // aplicado a la venta
  amountTendered: number;  // entregado por el cliente
  change: number;          // vuelto, solo en efectivo
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
| `SALE_WITHOUT_EMISSION_POINT` | 400 | Reenvío (o confirmación con Kafka activo) de una venta sin punto de emisión, anterior a S2.6 |

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
total_paid = Σ payment.amount          (lo aplicado, sin el vuelto)
if total_paid == 0:        PENDING
elif total_paid < total:   PARTIAL
else:                      PAID
```

`total_paid` y `total` se comparan redondeados al centavo.

### Pagos: aplicado, entregado y vuelto (S3.3)

El monto que se envía al registrar un pago (`POST /api/pos/sales/{id}/payments`, `payments[]` de la
venta rápida) es **lo que entrega el cliente**, redondeado al centavo. El core lo aplica así
(`Sale.take_payment` y `Sale.settle` en `src/sales/domain/entities.py`):

```
adeudado = total - Σ aplicado por los pagos anteriores
aplicado = min(entregado, adeudado)
vuelto   = entregado - aplicado
```

- Solo el efectivo puede superar lo adeudado; el resto es el vuelto. Otro medio de pago que lo supera,
  o un pago que llega con la venta ya cubierta, responde `400 PAYMENT_EXCEEDS_BALANCE`.
- Una venta `CANCELLED` o `INVOICED` no recibe pagos: `400 SALE_NOT_PAYABLE`.
- **Confirmar exige cobertura**: al confirmar, los pagos se vuelven a aplicar en el orden en que se
  registraron sobre el total final (los ítems de un borrador pueden cambiar después de cobrar) y deben
  cubrirlo; si no, `400 INSUFFICIENT_PAYMENT`. La venta queda `PAID`. Las ventas a crédito llegan en
  S5.5.
- Lo aplicado es lo que cuenta en la caja (resumen, X, Z, por medio de pago, cierre de turno) y lo que
  viaja a facturación: la suma de los pagos de `sales.confirmed` es igual al total de la venta.
- Los pagos anteriores a S3.3 guardaban lo entregado: la migración `f19314b5842a` pasó el excedente de
  las ventas pagadas de más (de sus pagos en efectivo, el último primero) al vuelto.

### Anulación y factura (S3.3, S3.4)

- `invoiceStatus` (`sales.invoice_status`) es la factura electrónica de la venta:
  - `PENDING` desde que el mensaje `sales.confirmed` de la venta entra al outbox, al confirmar con
    Kafka encendido o al reenviar. La respuesta del confirm, de la venta rápida y del reenvío ya lo
    muestra.
  - `REJECTED` cuando faclab-invoicing informa `InvoiceRejected`, con `invoiceRejectionReason` (los
    mensajes del SRI, campo `reason` de `invoices` v1) e `invoiceId`.
  - `AUTHORIZED` cuando informa `InvoiceAuthorized`: la venta pasa a `INVOICED`.
  - `null` si nunca se envió (Kafka apagado, o ventas anteriores a S3.3). Las facturadas antes de S3.4
    quedaron en `AUTHORIZED` con la migración.
- Reenviar una venta rechazada la deja en `PENDING` otra vez y borra el motivo, pero conserva
  `invoiceId`. Así, si Kafka repite el rechazo de esa factura después del reenvío, se ignora y no deja
  como rechazada la factura nueva.
- Una venta `CONFIRMED` con la factura pendiente no se cancela: `400 INVOICE_IN_PROGRESS`. Con la
  factura rechazada, o sin enviar (Kafka apagado o ventas anteriores a S3.3), se cancela como antes.
- Una venta `INVOICED` no se cancela: `400 CREDIT_NOTE_REQUIRED`. Se anula con nota de crédito (S4.5).

### Montos

El dinero se guarda como `numeric(18, 6)`: hasta 999.999.999.999,999999 por campo (antes de S3.3,
`numeric(12, 6)`, con tope de 999.999,99). Las APIs de administración y POS lo envían como número JSON;
los mensajes de Kafka (`contracts/`) y la API pública (S6.x) lo envían como texto decimal.
