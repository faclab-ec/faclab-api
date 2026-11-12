# Payables Module — API Specification (S5.7)

Especificación de las cuentas por pagar básicas para el frontend. Cada recepción de una orden de
compra abre una cuenta por lo recibido, con IVA, que vence según el plazo del proveedor. Su saldo
baja con los pagos al proveedor y con las devoluciones a proveedor confirmadas.

La cuenta de un proveedor muestra:

- lo que se le debe y lo vencido;
- sus cuentas abiertas;
- sus últimos pagos;
- sus devoluciones, con lo que acreditaron y lo que el proveedor debe reembolsar.

Es la contraparte de las cuentas por cobrar (S5.5, [receivables-spec.md](receivables-spec.md)), sin
cupo, antigüedad ni estado de cuenta (pendientes, ver ROADMAP).

---

## 1. Conceptos y enums

### Plazo del proveedor

Se configura en la ficha del proveedor (`PUT /api/admin/suppliers/{id}`):

| Campo          | Significado |
|----------------|-------------|
| `paymentTerms` | Plazo en días desde la recepción. Sin plazo, la cuenta vence el mismo día |

### PayableStatus

| Valor  | Descripción |
|--------|-------------|
| `OPEN` | Tiene saldo |
| `PAID` | Saldada, por pagos o devoluciones |

### PayableApplicationKind

| Valor     | Descripción |
|-----------|-------------|
| `PAYMENT` | Un pago al proveedor |
| `RETURN`  | Una devolución a proveedor confirmada, acreditada a la cuenta |

---

## 2. Cómo nacen y bajan las cuentas

### 2.1 Recepción

`POST /api/admin/purchase-orders/{id}/receive` ([purchasing-spec.md](purchasing-spec.md)) abre la
cuenta en la misma transacción de la recepción:

- **Monto:** el `total` de la recepción, es decir, lo recibido al costo de cada línea con el IVA de
  su tarifa. Cada tarifa se redondea a centavos, como la factura del proveedor.
- **Factura:** el `supplierInvoiceNumber` de la recepción, si vino.
- **Emisión:** el día de `receivedAt`.
- **Vencimiento:** la emisión más `paymentTerms` del proveedor (`termDays` queda en la cuenta).
- **Total 0:** una recepción sin costo (todo a 0,00) no abre cuenta.
- **Unicidad:** una sola cuenta por recepción (`uq_payables_tenant_purchase_receipt_id`).

Las recepciones anteriores a S5.7 no tienen cuenta.

### 2.2 Devolución a proveedor

Al confirmarse una devolución ([purchasing-spec.md](purchasing-spec.md#devoluciones-a-proveedor-s57)),
su total se acredita a las cuentas abiertas del proveedor:

- **Orden:** primero las de su orden de compra y después las demás, cada grupo de la que vence antes a
  la que vence después. Cada parte queda como una aplicación `RETURN`.
- **Excedente:** lo que no cabe en lo que se debe (porque ya se le pagó) queda en la devolución como
  `refundDue`, lo que el proveedor debe reembolsar. No hay saldo a favor.

### 2.3 Pago

```
POST /api/admin/supplier-payments            (payable:write)
{
  "supplierId": 10,
  "amount": 35.00,
  "paymentMethod": "TRANSFER",
  "reference": "TRF-881",
  "notes": null,
  "applications": [{ "payableId": 4, "amount": 35.00 }]
}
```

- **Sin `applications`:** se aplica FIFO, primero la cuenta que vence antes y, a igual vencimiento,
  la más antigua.
- **Con `applications`:** cada cuenta abierta del proveedor recibe lo que dice.
  - Ninguna puede pasar de su saldo, y entre todas deben sumar el pago
    (`SUPPLIER_PAYMENT_APPLICATION_MISMATCH`).
  - Una cuenta que no es del proveedor o no está abierta responde `PAYABLE_NOT_OPEN`.
- **Sin saldo a favor:** un pago mayor a lo que se debe responde `SUPPLIER_PAYMENT_EXCEEDS_BALANCE`.
- **Medio de pago:** `CREDIT` no se acepta (`CREDIT_PAYMENT_NOT_ALLOWED`). Un cheque va como `OTHER`,
  con su número en `reference`.
- **Numeración:** se numera por empresa, `PP-2026-0001` (`document_sequences`, `SUPPLIER_PAYMENT`).
- **Registro:** lo paga el usuario del token (`paidBy`) y queda en la bitácora como
  `supplier_payment.recorded`.
- **Concurrencia:** el pago bloquea las cuentas abiertas del proveedor (`FOR NO KEY UPDATE`, en
  orden de id). Dos pagos, o un pago y una devolución del mismo proveedor, se turnan, y el segundo
  ve los saldos que dejó el primero.
- **Fuera de la caja:** no toca la caja del POS ni ningún turno.

---

## 3. Endpoints (Admin)

Para leer hace falta `payable:read` (ADMIN, MANAGER, OPERATOR, VIEWER). Para pagar,
`payable:write` (ADMIN y MANAGER). El cajero no tiene ninguno de los dos.

### 3.1 Cuentas por pagar

```
GET /api/admin/payables?supplierId=10&status=OPEN&purchaseOrderId=1&overdue=true&limit=50&offset=0
```

| Query Param     | Tipo   | Default | Validación |
|-----------------|--------|---------|------------|
| supplierId      | int    | null    | >= 1 |
| status          | string | null    | PayableStatus |
| purchaseOrderId | int    | null    | >= 1 |
| overdue         | bool   | null    | `true`: abiertas y vencidas; `false`: el resto |
| limit           | int    | 100     | 1–1000 |
| offset          | int    | 0       | >= 0 |

La lista va de la cuenta que vence antes a la que vence después. Cada elemento es un `Payable` (§4).

```
GET /api/admin/payables/{id}
```

Devuelve la cuenta y lo que bajó su saldo (`applications`: pagos y devoluciones, con el número del
documento).

### 3.2 Cuenta de un proveedor

```
GET /api/admin/supplier-accounts/{supplierId}
```

Devuelve:

- lo que se le debe (`outstanding`) y lo vencido (`overdue`);
- sus cuentas abiertas (`payables`, para pagar);
- sus últimos 20 pagos (`payments`);
- sus últimas 20 devoluciones confirmadas (`returns`), con `creditedAmount` y `refundDue`.

### 3.3 Pagos

```
POST /api/admin/supplier-payments        (payable:write, 201)
GET  /api/admin/supplier-payments?supplierId=10
GET  /api/admin/supplier-payments/{id}
```

El POST sigue las reglas de §2.3. La lista va del último pago al primero. El detalle trae las cuentas
a las que se aplicó el pago, con el saldo que les queda hoy.

---

## 4. Formato de respuestas

### Payable

| Campo                   | Tipo     | Descripción |
|-------------------------|----------|-------------|
| `id`                    | int      | |
| `supplierId`            | int      | |
| `supplierName`          | string   | En la lista y el detalle |
| `supplierTaxId`         | string   | En la lista y el detalle |
| `purchaseOrderId`       | int      | |
| `orderNumber`           | string   | `PO-2026-0001` |
| `purchaseReceiptId`     | int      | La recepción que la abrió |
| `supplierInvoiceNumber` | string?  | Factura del proveedor de esa entrega |
| `amount`                | number   | Lo recibido con IVA |
| `balance`               | number   | Lo que todavía se debe |
| `issuedOn`              | date     | Día de la recepción |
| `dueOn`                 | date     | Vencimiento |
| `termDays`              | int      | El plazo del proveedor al recibir |
| `status`                | PayableStatus | |
| `daysOverdue`           | int      | Días de vencida mientras está abierta; 0 si no vence todavía |
| `createdAt`             | datetime | |

`GET /payables/{id}` agrega `applications`:

| Campo               | Tipo     | Descripción |
|---------------------|----------|-------------|
| `id`                | int      | |
| `kind`              | PayableApplicationKind | |
| `amount`            | number   | |
| `appliedAt`         | datetime | |
| `supplierPaymentId` | int?     | Si es un pago |
| `supplierReturnId`  | int?     | Si es una devolución |
| `documentNumber`    | string?  | `PP-2026-0001` o `DP-2026-0001` |
| `paymentMethod`     | PaymentMethod? | El del pago |

### SupplierPayment

| Campo           | Tipo          | Descripción |
|-----------------|---------------|-------------|
| `id`            | int           | |
| `number`        | string        | `PP-2026-0001` |
| `supplierId`    | int           | |
| `supplierName`  | string?       | |
| `amount`        | number        | |
| `paymentMethod` | PaymentMethod | Cualquiera menos `CREDIT` |
| `reference`     | string?       | Número de transferencia o cheque, hasta 128 caracteres |
| `notes`         | string?       | Hasta 512 caracteres |
| `paidAt`        | datetime      | |
| `paidBy`        | string?       | Nombre del usuario del token |

`POST` y `GET /{id}` agregan `applications`: `payableId`, `purchaseOrderId`,
`supplierInvoiceNumber`, `amount` y `balance` (el saldo de la cuenta después del pago, o hoy en el
detalle).

### SupplierAccount

| Campo            | Tipo                | Descripción |
|------------------|---------------------|-------------|
| `supplierId`     | int                 | |
| `supplierName`   | string              | |
| `supplierTaxId`  | string              | |
| `paymentTerms`   | int?                | Días |
| `outstanding`    | number              | Lo que se le debe |
| `overdue`        | number              | Lo que se le debe vencido |
| `payables`       | Payable[]           | Cuentas abiertas, la que vence antes primero |
| `payments`       | SupplierPayment[]   | Últimos 20, el último primero |
| `returns`        | SupplierReturnCredit[] | Últimas 20 confirmadas: `id`, `number`, `purchaseOrderId`, `orderNumber`, `supplierCreditNoteNumber`, `total`, `creditedAmount`, `refundDue`, `confirmedAt` |

---

## 5. Errores

| Código HTTP | `errorCode` | Caso |
|-------------|-------------|------|
| 400 | `SUPPLIER_PAYMENT_EXCEEDS_BALANCE` | El pago supera lo que se le debe al proveedor |
| 400 | `PAYABLE_NOT_OPEN` | Una aplicación a una cuenta pagada o de otro proveedor |
| 400 | `SUPPLIER_PAYMENT_APPLICATION_MISMATCH` | Las aplicaciones no suman el pago o pasan un saldo |
| 400 | `CREDIT_PAYMENT_NOT_ALLOWED` | Pago con `CREDIT` |
| 404 | `NOT_FOUND` | Proveedor, cuenta o pago inexistente |
| 403 | `PERMISSION_DENIED` | Sin `payable:read` / `payable:write` |
