# Ventas desde un ecommerce

Un pedido pagado en la tienda en línea se registra con `POST /api/v1/sales` (`sales:write`): Faclab
crea la venta, descuenta el stock, la numera en su sucursal (`V-001-000123`) y la envía a facturar,
todo en una operación, con las mismas reglas que el punto de venta.

## Dónde se vende

`GET /api/v1/branches` lista las sucursales del cliente con sus **puntos de emisión** y
**ubicaciones**. La venta indica la sucursal en `X-Branch-Id` y, en el cuerpo, el punto de emisión
(`emissionPointId`, el que numera su factura) y la ubicación de la que sale el stock (`locationId`).
Conviene que el ecommerce tenga su propio punto de emisión.

## El pedido

```http
POST /api/v1/sales
Authorization: Bearer <token>
X-Branch-Id: 12
Idempotency-Key: 0b7c5e2a-3f1d-4c8e-9a6b-2d4f8e1c7a90

{
  "emissionPointId": 31,
  "locationId": 44,
  "externalReference": "WEB-100234",
  "customer": {"identification": "1712345678"},
  "items": [{"productId": 501, "quantity": "3"}],
  "payments": [{"method": "TRANSFER", "amount": "14.28", "reference": "pasarela-7f3a"}]
}
```

- **Cliente**: por `id` o por `identification` (créalo antes con `POST /api/v1/customers`, que
  responde 409 `CUSTOMER_ALREADY_EXISTS` con `existingId` si ya existe). Sin `customer`, se vende al
  consumidor final.
- **Líneas**: `productId`, `quantity` y opcionalmente `presentationId` (la unidad base por defecto) y
  `discountPercent`. El precio es el de sus listas; otro `unitPrice` exige `overrideReason` y queda en
  la bitácora de auditoría con el cliente de integración como autor.
- **Pagos**: la venta llega **pagada en línea**: `CREDIT_CARD`, `DEBIT_CARD`, `TRANSFER` u `OTHER`,
  con la referencia de la pasarela, por el **total con IVA exacto** (`INSUFFICIENT_PAYMENT` o
  `PAYMENT_EXCEEDS_BALANCE` si no). Efectivo y crédito no se aceptan. El total lo calcula Faclab:
  léelo de la respuesta.
- **Stock**: si no alcanza, 400 `INSUFFICIENT_STOCK` y nada cambia.

La respuesta (201) trae la venta confirmada con su número, totales, ítems, pagos e `invoiceStatus`
(`PENDING` mientras se factura).

## Reintentos

Genera un `Idempotency-Key` (UUID) por pedido y repítelo en cada reintento del mismo pedido: la
venta se crea una sola vez y el reintento recibe la misma respuesta con `Idempotent-Replayed: true`.
La misma clave con otro cuerpo responde 422 `IDEMPOTENCY_KEY_REUSED`; mientras la primera sigue en
curso, el reintento espera o, tras 10 s, recibe 409 `IDEMPOTENCY_IN_PROGRESS`. Los errores no se
guardan: un reintento después de un error vuelve a intentarlo. `externalReference` permite además
encontrar la venta de un pedido (`GET /api/v1/sales?externalReference=WEB-100234`).

## Anular

`POST /api/v1/sales/{id}/cancel` anula una venta que creó el mismo cliente (otra: 403
`PERMISSION_DENIED`) y devuelve el stock. Solo antes de que su factura esté en camino: mientras
facturación la tiene, 400 `INVOICE_IN_PROGRESS`; una vez autorizada necesita una nota de crédito
(`CREDIT_NOTE_REQUIRED`), que por ahora se emite desde Faclab.

## La factura

`GET /api/v1/sales/{id}` trae `invoiceStatus` (`PENDING`, `AUTHORIZED`, `REJECTED`) e `invoiceId`.
Con `invoices:read`, `GET /api/v1/invoices?saleId={id}` lista sus comprobantes y
`/api/v1/invoices/{invoiceId}/xml` y `/ride` descargan el XML autorizado y el PDF. Hasta que lleguen
los webhooks (S6.4), consulta el estado periódicamente.
