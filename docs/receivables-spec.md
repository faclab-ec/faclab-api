# Receivables Module — API Specification (S5.5)

Especificación de las ventas a crédito y las cuentas por cobrar para el frontend. Una venta del POS
puede dejar una parte (o todo) a crédito con un pago `CREDIT`, dentro del cupo del cliente. Esa parte
abre una cuenta por cobrar que vence según el plazo del cliente. Su saldo baja con los abonos, en la
caja de un turno o fuera de ella, y con las devoluciones de la venta. La cartera muestra la antigüedad
de los saldos y el estado de cuenta de cada cliente.

Las ventas de administración siguen siendo de solo lectura (G-34): toda venta nace en una terminal del
POS, así que el crédito se da en el POS (venta rápida, confirmar un borrador o cobrar una cotización).

---

## 1. Conceptos y enums

### Crédito del cliente

Se configura en la ficha del cliente (`PUT /api/admin/customers/{id}`):

| Campo          | Significado |
|----------------|-------------|
| `creditLimit`  | Cupo: lo máximo que puede deber. Sin cupo (nulo o 0), no compra a crédito |
| `paymentTerms` | Plazo en días desde la venta. Sin plazo, la cuenta vence el mismo día |

Un cliente inactivo no compra a crédito. El consumidor final tampoco (`CREDIT_CUSTOMER_REQUIRED`).

### PaymentMethod `CREDIT`

`CREDIT` es lo que el cliente queda debiendo. Se aplica como cualquier medio que no es efectivo: no da
vuelto ni puede pasar de lo que se debe. Los pagos, con el crédito, cubren el total. La venta queda
pendiente de cobro (`paymentStatus` `PENDING`) o parcial (`PARTIAL`) si pagó una parte, y pasa a `PAID`
cuando su cuenta se salda.

### ReceivableStatus

| Valor       | Descripción |
|-------------|-------------|
| `OPEN`      | Tiene saldo |
| `PAID`      | Saldada, por abonos o devoluciones |
| `CANCELLED` | Su venta se anuló antes de recibir abonos |

### ReceivableApplicationKind

| Valor     | Descripción |
|-----------|-------------|
| `PAYMENT` | Un abono del cliente |
| `REFUND`  | Una devolución de la venta, acreditada a la cuenta |

### Antigüedad (días de vencido a hoy)

| Campo        | Tramo |
|--------------|-------|
| `notDue`     | Por vencer: vence hoy o después |
| `days1To30`  | 1 a 30 días de vencida |
| `days31To60` | 31 a 60 |
| `days61To90` | 61 a 90 |
| `over90`     | Más de 90 |

Cada cuenta abierta cae en un solo tramo: los tramos suman lo que se debe.

---

## 2. Venta a crédito en el POS

### 2.1 Cupo disponible

```
GET /api/pos/customer-accounts/{customerId}        (pos:operate)
```

Responde la cuenta del cliente (§5, `CustomerAccount`): `hasCredit`, `available` (cupo menos lo que
debe) y sus cuentas abiertas. El POS la usa para habilitar el pago a crédito y para abonar.

### 2.2 Vender a crédito

Con la venta rápida o al confirmar un borrador, uno de los pagos es `CREDIT`:

```
POST /api/pos/sales/quick
Idempotency-Key: <uuid>
{
  "customerId": 7,
  "items": [{ "productId": 12, "quantity": 10 }],
  "payments": [
    { "amount": 20.00, "paymentMethod": "CASH" },
    { "amount": 95.00, "paymentMethod": "CREDIT" }
  ]
}
```

- En la misma transacción de la venta:
  - el core bloquea la fila del cliente (después del stock y antes del contador);
  - comprueba que lo que debe más el crédito nuevo no pase su cupo (`CREDIT_LIMIT_EXCEEDED`);
  - abre la cuenta por cobrar con el plazo del cliente.
- Dos ventas a crédito simultáneas del mismo cliente se turnan: la segunda cuenta la cuenta de la
  primera.
- La respuesta trae el pago `CREDIT` con `termDays` (el plazo) y la venta en `PENDING` o `PARTIAL`.
- La cotización cobrada (`quoteId`) admite crédito igual.
- La factura lleva la parte a crédito como `formaPago` 20 con `plazo` y `unidadTiempo` `dias`
  (`sales.confirmed` v3, ver `contracts/CHANGELOG.md`).

### 2.3 Devolución de una venta a crédito

- **Al crear la devolución** (`POST /api/pos/refunds`) la respuesta trae `accountCredit`: lo que
  procesarla ahora acreditaría a la cuenta (hasta su saldo).
- **Al procesarla** (`POST /api/pos/refunds/{id}/process`):
  - el core acredita la devolución a la cuenta y registra un pago de devolución `CREDIT` por ese monto;
  - los `payments` del request devuelven exactamente el resto: lista vacía si todo cabe en el saldo;
  - si no suman eso, responde `VALIDATION_ERROR` 422;
  - un pago `CREDIT` en el request responde `CREDIT_PAYMENT_NOT_ALLOWED` 400.
- **Una cuenta ya saldada** no acredita nada: la devolución se devuelve en dinero como siempre.

### 2.4 Anulación

Una venta a crédito confirmada se anula (`POST /api/pos/sales/{id}/cancel`) solo si su cuenta no bajó.
Entonces la cuenta pasa a `CANCELLED`. Con abonos o devoluciones acreditadas, la anulación responde
`RECEIVABLE_HAS_PAYMENTS`: se devuelve en lugar de anularse.

### 2.5 Abono en la caja

```
POST /api/pos/customer-payments            (pos:operate, X-Branch-Id + X-Terminal-Id)
Idempotency-Key: <uuid>
{
  "customerId": 7,
  "amount": 40.00,
  "paymentMethod": "CASH",
  "reference": null,
  "notes": "Abono semanal",
  "applications": [{ "receivableId": 3, "amount": 40.00 }]
}
```

- Va al turno abierto de la terminal (`NO_OPEN_SHIFT` sin él).
- En efectivo, cuenta en la caja del turno: `customerPayments` del resumen de caja, del cierre y del Z
  (§4).
- Sin `applications`, se aplica FIFO: primero la cuenta que vence antes y, a igual vencimiento, la
  más antigua.
- Con `applications`, cada cuenta abierta del cliente recibe lo que dice:
  - ninguna puede pasar de su saldo;
  - deben sumar el abono (`PAYMENT_APPLICATION_MISMATCH`);
  - una que no es del cliente o no está abierta responde `RECEIVABLE_NOT_OPEN`.
- No hay saldo a favor: un abono mayor a lo que se debe responde `CUSTOMER_PAYMENT_EXCEEDS_BALANCE`.
- `CREDIT` no se acepta (`CREDIT_PAYMENT_NOT_ALLOWED`).
- Se numera por empresa: `AB-2026-0001`.
- Lo recibe el usuario del token (`receivedBy`).
- Queda en la bitácora como `customer_payment.recorded`.

---

## 3. Endpoints (Admin)

Leer exige `receivable:read` (ADMIN, MANAGER, OPERATOR, VIEWER) y abonar fuera de caja
`receivable:write` (ADMIN, MANAGER, OPERATOR). El cajero abona en el POS con `pos:operate`.

### 3.1 Cuentas por cobrar

```
GET /api/admin/receivables?customerId=7&status=OPEN&overdue=true&branchId=1&limit=50&offset=0
```

| Query Param | Tipo   | Default | Validación |
|-------------|--------|---------|------------|
| customerId  | int    | null    | >= 1 |
| status      | string | null    | ReceivableStatus |
| overdue     | bool   | null    | `true`: abiertas y vencidas; `false`: el resto |
| branchId    | int    | null    | >= 1 |
| limit       | int    | 100     | 1–1000 |
| offset      | int    | 0       | >= 0 |

La que vence antes primero. Cada elemento es un `Receivable` (§5).

```
GET /api/admin/receivables/{id}
```

La cuenta y lo que bajó su saldo (`applications`: abonos y devoluciones, con el número del documento).

### 3.2 Antigüedad de saldos

```
GET /api/admin/receivables/aging?branchId=1
```

Lo que debe cada cliente por tramo (§1), el que más debe primero, y los totales. `branchId` filtra por
la sucursal de la venta.

### 3.3 Cuenta y estado de cuenta de un cliente

```
GET /api/admin/customer-accounts/{customerId}
GET /api/admin/customer-accounts/{customerId}/statement?fromDate=2026-11-01&toDate=2026-11-30
```

El estado de cuenta tiene:

- el saldo al empezar el período (`openingBalance`);
- cada movimiento con el saldo después de él:
  - venta a crédito (`SALE`, cargo);
  - abono (`PAYMENT`);
  - devolución acreditada (`REFUND`);
  - venta anulada (`CANCELLATION`);
- el saldo al terminar (`closingBalance`). Sin `toDate`, es lo que el cliente debe hoy.

Las fechas son días completos.

### 3.4 Abonos

```
POST /api/admin/customer-payments        (receivable:write)
GET  /api/admin/customer-payments?customerId=7
GET  /api/admin/customer-payments/{id}
```

- El POST es el abono fuera de caja (transferencia, cheque, efectivo en oficina).
- Tiene el mismo cuerpo y las mismas reglas que el del POS (§2.5).
- No cuenta en ningún turno. Lleva la sucursal de `X-Branch-Id`, si viene.
- No pide `Idempotency-Key`.

---

## 4. Caja y reportes del POS

- **Resumen de caja** (`GET /api/pos/shifts/{id}/cash-summary`) y **arqueo del Z**
  (`cashReconciliation`) agregan `customerPayments`, los abonos en efectivo del turno:

  ```
  expectedBalance = openingBalance + cashSales - cashRefunds + customerPayments + cashIn - cashOut
  ```

  El cierre del turno usa la misma fórmula.
- **Reportes X y Z** agregan `customerPaymentsByMethod`: los abonos del turno por medio de pago. En
  `paymentsByMethod`, `CREDIT` es lo que se vendió a crédito, que no entra en la caja.
- **Pagos de devolución** `CREDIT` (lo acreditado a la cuenta) tampoco salen de la caja.

---

## 5. Formato de respuestas

### Receivable

| Campo           | Tipo     | Descripción |
|-----------------|----------|-------------|
| `id`            | int      | |
| `customerId`    | int      | |
| `customerName`  | string   | En la lista y el detalle |
| `customerTaxId` | string   | En la lista y el detalle |
| `saleId`        | int      | |
| `saleNumber`    | string   | `V-001-000123` |
| `branchId`      | int?     | Sucursal de la venta |
| `amount`        | number   | Lo que la venta dejó a crédito |
| `balance`       | number   | Lo que todavía se debe |
| `issuedOn`      | date     | Día de la venta |
| `dueOn`         | date     | `issuedOn` + `termDays` |
| `termDays`      | int      | |
| `status`        | ReceivableStatus | |
| `cancelledAt`   | datetime?| |
| `daysOverdue`   | int      | Días de vencida mientras está abierta; 0 si no vence |

### CustomerAccount

`customerId`, `customerName`, `customerTaxId`, `creditLimit` (nulo sin cupo), `paymentTerms`,
`hasCredit`, `outstanding` (lo que debe), `overdue` (lo vencido), `available` y `receivables` (las
abiertas, la que vence antes primero).

### Statement

`customerId`, `customerName`, `customerTaxId`, `fromDate`, `toDate`, `openingBalance`, `lines[]`
(`type`, `id`, `date`, `documentNumber`, `charge`, `credit`, `balance`, `receivableId`, `saleId`,
`customerPaymentId`, `refundId`, `dueOn` y `paymentMethod`, estos dos según el tipo) y
`closingBalance`.

### CustomerPayment

| Campo           | Tipo     | Descripción |
|-----------------|----------|-------------|
| `id`            | int      | |
| `number`        | string   | `AB-2026-0001` |
| `customerId`    | int      | |
| `customerName`  | string   | |
| `amount`        | number   | |
| `paymentMethod` | PaymentMethod | Nunca `CREDIT` |
| `reference`     | string?  | |
| `notes`         | string?  | |
| `paidAt`        | datetime | |
| `receivedBy`    | string   | Nombre del usuario del token |
| `branchId`      | int?     | |
| `terminalId`    | int?     | En el POS |
| `shiftId`       | int?     | El turno cuya caja lo recibió |
| `applications`  | array    | `receivableId`, `saleId`, `saleNumber`, `amount`, `balance` (el de la cuenta ahora); no viene en la lista |

---

## 6. Manejo de errores

| Código | HTTP | Cuándo |
|--------|------|--------|
| `CREDIT_LIMIT_EXCEEDED` | 400 | Lo que debe más el crédito nuevo pasa el cupo (el `detail` trae cupo, saldo, disponible y monto) |
| `CUSTOMER_WITHOUT_CREDIT` | 400 | Cliente inactivo o sin cupo |
| `CREDIT_CUSTOMER_REQUIRED` | 400 | Pago `CREDIT` en una venta a consumidor final |
| `CUSTOMER_PAYMENT_EXCEEDS_BALANCE` | 400 | El abono pasa lo que el cliente debe |
| `PAYMENT_APPLICATION_MISMATCH` | 400 | La aplicación manual no suma el abono o pasa el saldo de una cuenta |
| `RECEIVABLE_NOT_OPEN` | 400 | La cuenta de la aplicación no es del cliente o no está abierta |
| `RECEIVABLE_HAS_PAYMENTS` | 400 | Anular una venta a crédito con abonos o devoluciones acreditadas |
| `CREDIT_PAYMENT_NOT_ALLOWED` | 400 | `CREDIT` en un abono o en los pagos de una devolución |
| `NO_OPEN_SHIFT` | 400 | Abono en el POS sin turno abierto en la terminal |
| `NOT_FOUND` | 404 | Cliente, cuenta o abono de otra empresa o inexistente |

---

## 7. Fuera de alcance (pendiente)

Detalle en ROADMAP.md, "Crédito y cuentas por cobrar, lo que quedó de S5.5":

- Anular un abono.
- Saldo a favor.
- Bloquear el crédito con saldo vencido.
- Antigüedad a una fecha pasada.
- Recibo imprimible del abono.
- Abonos en los reportes diario y por medio de pago.
- Ventas a crédito fuera del POS.
