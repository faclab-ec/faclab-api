# Quotes Module — API Specification (S5.4)

Especificación de las cotizaciones (proformas) para el frontend: se crean en el admin, numeradas por
sucursal, con los precios de las listas del cliente; se imprimen o envían en PDF y se cobran en el POS
como una venta con sus mismos ítems. Reservar stock no está en el alcance: la venta lo descuenta al
cobrarse y puede faltar.

---

## 1. Enums

### QuoteStatus

| Valor       | Descripción |
|-------------|-------------|
| `DRAFT`     | Borrador: se editan su cabecera y sus ítems, y se puede borrar |
| `SENT`      | Entregada al cliente, a mano (`/send`) o por correo (`/email`) |
| `ACCEPTED`  | El cliente la aceptó |
| `EXPIRED`   | Pasó su fecha sin cobrarse; se renueva para volver a usarla |
| `CONVERTED` | Se cobró en el POS (ver `saleId`) |

Una cotización abierta (`DRAFT`, `SENT`, `ACCEPTED`) cuya `validUntil` ya pasó se trata como vencida
aunque el worker todavía no la haya marcado `EXPIRED` (lo hace cada hora).

```
DRAFT ──send/email──▶ SENT ──accept──▶ ACCEPTED ──venta rápida con quoteId──▶ CONVERTED
  │  └──accept──────────────────────────▲   (también desde DRAFT o SENT)
  └──(fecha pasada, cualquiera abierta)──▶ EXPIRED ──renew──▶ DRAFT
```

---

## 2. Endpoints (Admin)

Base URL: `/api/admin/quotes`. Leer exige `sale:read`; el resto, `sale:write`. Solo se ven las
cotizaciones de las sucursales a las que el usuario puede entrar: las de otra responden 404.

### 2.1 Listar

```
GET /api/admin/quotes?status=SENT&customerId=6&branchId=1&number=0012&limit=20&offset=0
```

| Query Param | Tipo   | Default | Validación |
|-------------|--------|---------|------------|
| status      | string | null    | QuoteStatus |
| customerId  | int    | null    | >= 1 |
| branchId    | int    | null    | una sucursal del usuario (`BRANCH_ACCESS_DENIED` 403) |
| number      | string | null    | parte del número |
| limit       | int    | 100     | 1–1000 |
| offset      | int    | 0       | >= 0 |

Las más nuevas primero. Cada elemento es un `QuoteSummary` (§3).

### 2.2 Crear

```
POST /api/admin/quotes
{ "branchId": 1, "customerId": 6, "validUntil": "2026-11-26", "notes": "Obra Calderón" }
```

| Campo      | Tipo   | Requerido | Validación |
|------------|--------|-----------|------------|
| branchId   | int    | sí | activa (`BRANCH_INACTIVE` 409) y del usuario (`BRANCH_ACCESS_DENIED` 403) |
| customerId | int    | no | sin él: consumidor final |
| validUntil | date   | sí | hoy o después (422) |
| notes      | string | no | máx. 1024, se imprimen |

Crea un borrador emitido hoy y numerado en la sucursal (`COT-001-000012`). El autor sale del token.
**Response** `200`: `Quote` (§3) sin ítems.

### 2.3 Obtener, editar, borrar

```
GET    /api/admin/quotes/{id}
PUT    /api/admin/quotes/{id}   { "customerId": 6, "validUntil": "2026-11-26", "notes": null }
DELETE /api/admin/quotes/{id}
```

`PUT` y `DELETE` solo en `DRAFT` (`INVALID_QUOTE_STATUS` 400). `PUT` reemplaza cliente, vigencia y
notas; con otro cliente, todos los ítems toman los precios de sus listas. Un borrador borrado deja su
número sin reutilizar.

### 2.4 Ítems

```
POST   /api/admin/quotes/{id}/items             { "productId": 100, "presentationId": 21, "quantity": 3, "discount": 0 }
PUT    /api/admin/quotes/{id}/items/{itemId}    { "quantity": 10, "discount": 5 }
DELETE /api/admin/quotes/{id}/items/{itemId}
```

Solo en `DRAFT`. La línea toma el precio que tendría hoy una venta de su cliente en su sucursal: la
lista del cliente, la de la sucursal o la general, o el de su presentación (S5.3). No se envía precio;
sin ninguno responde `PRODUCT_WITHOUT_PRICE` (400). La cantidad va en su presentación (sin
`presentationId`: la unidad base) con los decimales de su unidad (`QUANTITY_PRECISION_EXCEEDED` 422).
Cambiar la cantidad aplica la escala que corresponda. `discount` es el % de la línea (0–100). Las tres
responden la cotización completa con sus totales nuevos.

### 2.5 Acciones

| Método y ruta | Body | Efecto |
|---|---|---|
| `POST /{id}/send` | — | `DRAFT` → `SENT` (entregada impresa o a mano) |
| `POST /{id}/accept` | — | `DRAFT`/`SENT` → `ACCEPTED` |
| `POST /{id}/email` | `{ "to": "compras@andes.ec" }` | envía el PDF; un `DRAFT` pasa a `SENT` |
| `POST /{id}/renew` | `{ "validUntil": "2026-12-15" }` | una vencida vuelve a `DRAFT`, emitida hoy y con los precios de hoy |

`send`, `accept` y `email` exigen ítems (`QUOTE_WITHOUT_ITEMS`) y vigencia (`QUOTE_EXPIRED`). `email`:
sin `to` va al correo del cliente (`QUOTE_EMAIL_REQUIRED` 422 si no tiene); un `SENT` o `ACCEPTED` se
puede reenviar. El servidor SMTP responde dentro de la solicitud: si rechaza el mensaje o no
responde, `EMAIL_DELIVERY_FAILED` (502) y nada cambia; con el correo apagado, `EMAIL_DISABLED` (400).
`renew` solo con una vencida (`INVALID_QUOTE_STATUS`).

### 2.6 PDF

```
GET /api/admin/quotes/{id}/pdf   → 200 application/pdf (attachment; filename="cotizacion-COT-001-000012.pdf")
```

En cualquier estado. A4: empresa (nombre comercial, razón social, RUC), sucursal, número, fechas de
emisión y validez, cliente (o consumidor final), ítems (código, descripción con la presentación,
cantidad, precio unitario, descuento, subtotal), subtotal por tarifa de IVA, IVA, total y notas. Pie:
"Documento sin valor tributario… la cotización no reserva mercadería". La web nombra el archivo con el
número (el encabezado `Content-Disposition` no se expone por CORS).

---

## 3. Formato de respuestas

### QuoteSummary

```json
{
  "id": 12,
  "number": "COT-001-000012",
  "branchId": 1,
  "branchName": "Matriz",
  "establishmentCode": "001",
  "customerId": 6,
  "customerName": "Constructora Andes",
  "customerTaxId": "1790012345001",
  "customerEmail": "compras@andes.ec",
  "status": "SENT",
  "issueDate": "2026-11-11",
  "validUntil": "2026-11-26",
  "subtotal": 99.0,
  "tax": 14.85,
  "total": 113.85,
  "notes": "Obra Calderón",
  "createdBy": "Ana Pérez",
  "sentAt": "2026-11-11T10:20:00",
  "acceptedAt": null,
  "convertedAt": null
}
```

### Quote

`QuoteSummary` más:

```json
{
  "items": [
    {
      "id": 31,
      "quoteId": 12,
      "productId": 100,
      "productName": "Cemento",
      "productSku": "FERR-003",
      "presentationId": 10,
      "presentationName": "Saco",
      "quantity": 10,
      "unitFactor": 1,
      "baseQuantity": 10,
      "unitPrice": 8.9,
      "discount": 0,
      "taxCode": "VAT_15",
      "taxAmount": 13.35,
      "subtotal": 89.0
    }
  ],
  "saleId": null,
  "saleNumber": null
}
```

Los totales se calculan como los de una venta sin descuento global: subtotal a centavos, IVA por tarifa
redondeado por grupo, `total = subtotal + tax`.

---

## 4. Cobro en el POS

Base URL: `/api/pos/quotes` (`pos:operate`).

### 4.1 Vigentes de la sucursal

```
GET /api/pos/quotes?search=andes&limit=20     (X-Branch-Id)
```

Las abiertas de la sucursal de `X-Branch-Id` que rigen hoy, las más nuevas primero; `search` busca en
el número y en el nombre o RUC/cédula del cliente. Elementos `QuoteSummary`.

### 4.2 Una cotización para cobrarla

```
GET /api/pos/quotes/{id}     (X-Branch-Id + X-Terminal-Id)
```

Solo de la sucursal de la terminal (otra responde 404). `Quote` más `expired` y, por ítem:

| Campo | Descripción |
|---|---|
| `listPrice` | el precio de hoy para su cliente (null: ninguno) |
| `priceListName` | la lista que lo da (null: el del producto) |
| `priceChanged` | el cotizado no es el de hoy |
| `availableQuantity` | stock disponible del producto en la ubicación de la terminal, en unidades base (no reservado) |
| `enoughStock` | alcanza para lo que piden todas sus líneas del producto |

### 4.3 Cobrarla

Con la venta rápida (`POST /api/pos/sales/quick`, ver `pos-api-spec.md`) y `quoteId`:

```json
{
  "quoteId": 12,
  "customerId": 6,
  "items": [
    { "productId": 100, "presentationId": 10, "quantity": 10, "unitPrice": 8.9, "overrideReason": "Cotización COT-001-000012" },
    { "productId": 200, "quantity": 5 }
  ],
  "payments": [{ "amount": 113.85, "paymentMethod": "CASH" }]
}
```

- La cotización debe regir (`QUOTE_EXPIRED`: renovarla antes), ser de la sucursal de la terminal
  (`QUOTE_OUTSIDE_BRANCH`), no estar cobrada (`QUOTE_ALREADY_CONVERTED` 409) y la venta debe ser de su
  cliente (`QUOTE_CUSTOMER_CHANGED`) con sus mismos ítems: producto, presentación, cantidad y descuento
  (`QUOTE_ITEMS_CHANGED`). Todos 400 salvo el indicado.
- Si un precio cambió (`priceChanged`), el cajero elige: **respetar el cotizado** (la línea lleva
  `unitPrice` cotizado y `overrideReason` `Cotización <número>`, que queda en la bitácora como
  `sale.price_overridden`) o **cobrar el actual** (sin `unitPrice`).
- El stock se valida al descontarlo (`INSUFFICIENT_STOCK`).
- La venta queda con `quoteId` (en `GET /api/admin/sales/{id}`) y la cotización `CONVERTED` con
  `saleId` y `saleNumber`.

---

## 5. Tipos TypeScript (referencia frontend)

```ts
type QuoteStatus = 'DRAFT' | 'SENT' | 'ACCEPTED' | 'EXPIRED' | 'CONVERTED'

interface QuoteSummary {
  id: number
  number: string | null
  branchId: number
  branchName: string | null
  establishmentCode: string | null
  customerId: number | null
  customerName: string | null
  customerTaxId: string | null
  customerEmail: string | null
  status: QuoteStatus
  issueDate: string
  validUntil: string
  subtotal: number
  tax: number
  total: number
  notes: string | null
  createdBy: string | null
  sentAt: string | null
  acceptedAt: string | null
  convertedAt: string | null
}

interface QuoteItem {
  id: number
  quoteId: number
  productId: number
  productName: string | null
  productSku: string | null
  presentationId: number | null
  presentationName: string | null
  quantity: number
  unitFactor: number
  baseQuantity: number
  unitPrice: number
  discount: number
  taxCode: string
  taxAmount: number
  subtotal: number
}

interface Quote extends QuoteSummary {
  items: QuoteItem[]
  saleId: number | null
  saleNumber: string | null
}

interface PosQuoteItem extends QuoteItem {
  listPrice: number | null
  priceListName: string | null
  priceChanged: boolean
  availableQuantity: number
  enoughStock: boolean
}

interface PosQuote extends Omit<Quote, 'items'> {
  items: PosQuoteItem[]
  expired: boolean
}
```

---

## 6. Manejo de errores

| Código | HTTP | Cuándo |
|---|---|---|
| `INVALID_QUOTE_STATUS` | 400 | editar, borrar o agregar ítems fuera de `DRAFT`; aceptar una aceptada; renovar una vigente |
| `QUOTE_WITHOUT_ITEMS` | 400 | enviar o aceptar sin ítems |
| `QUOTE_EXPIRED` | 400 | enviar, aceptar o cobrar una vencida |
| `PRODUCT_WITHOUT_PRICE` | 400 | un producto sin precio en sus listas ni propio |
| `QUOTE_EMAIL_REQUIRED` | 422 | correo sin destinatario |
| `EMAIL_DISABLED` | 400 | `EMAIL_ENABLED=false` |
| `EMAIL_DELIVERY_FAILED` | 502 | el servidor SMTP rechazó o no respondió |
| `QUOTE_OUTSIDE_BRANCH` | 400 | cobrarla en otra sucursal |
| `QUOTE_CUSTOMER_CHANGED` | 400 | la venta es de otro cliente |
| `QUOTE_ITEMS_CHANGED` | 400 | la venta no lleva sus mismos ítems |
| `QUOTE_ALREADY_CONVERTED` | 409 | ya se cobró |

---

## 7. Fuera de alcance (pendiente)

Reservar stock; conversión parcial o con ítems cambiados; estados de rechazada o anulada; descuento
global y precios a mano en la cotización; volver a cobrarla si se anula su venta; bitácora y
reintentos asíncronos del correo; logo en el PDF; formato del número configurable por empresa;
cotizaciones a crédito (S5.5).
