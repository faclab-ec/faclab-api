# Facturas por webhook

Faclab emite la factura electrónica de cada venta, también las que llegan por la API, y la envía al
SRI. La autorización tarda de segundos a horas, según el SRI. Esta guía muestra cómo enterarte con
un webhook, sin consultar, y cómo descargar el XML y el RIDE para tu cliente.

## 1. El flujo

1. `POST /api/v1/sales` crea la venta confirmada, con `invoiceStatus: PENDING`.
2. Faclab firma la factura y la envía al SRI.
3. Si el SRI la autoriza, llega `invoice.authorized` con el `invoiceId`. Con él pides la factura,
   su XML y su RIDE.
4. Si la rechaza, llega `invoice.rejected` con el motivo.

En el sandbox las facturas van al **ambiente de pruebas del SRI**: se autorizan igual, pero no tienen
valor tributario.

## 2. Suscríbete

Tu cliente necesita `invoices:read`. Registra un endpoint con estos eventos, en la aplicación
(**Configuración → Webhooks**) o por la API:

```bash
curl -s "$FACLAB_API_URL/api/v1/webhook-endpoints" \
  -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://tienda.example/webhooks/faclab",
       "eventTypes": ["invoice.authorized", "invoice.rejected", "credit_note.authorized"]}'
```

`excludeOwnChanges` no afecta a estos eventos. La factura de una venta que creaste la autoriza el
SRI, no tu solicitud, así que te llega igual.

## 3. Recibe `invoice.authorized`

```json
{"id": "msg_2f9a…", "type": "invoice.authorized", "version": 1,
 "occurredAt": "2026-11-18T15:04:05.000Z", "tenantId": "8d1c…", "originClientId": null,
 "data": {"invoiceId": 812, "saleId": 4501, "saleNumber": "V-001-000123", "branchId": 12,
          "externalReference": "WEB-100234"}}
```

`externalReference` es el número de pedido que enviaste al crear la venta: con él encuentras el
pedido en tu sistema. Lo que haces al recibirlo:

1. **Comprueba la firma** y responde **2xx enseguida**, en menos de 10 segundos (ver **Webhooks**).
   Descarga la factura después, fuera de esa solicitud.
2. **Deduplica por `webhook-id`**. Un reintento trae el mismo id: si ya lo procesaste, ignóralo.
3. **Pide la factura** con su `invoiceId`:

```bash
curl -s "$FACLAB_API_URL/api/v1/invoices/812" -H "Authorization: Bearer $TOKEN"
# {"data": {"id": 812, "documentType": "INVOICE", "number": "001-001-000000123",
#           "accessCode": "1811…", "status": "AUTHORIZED", "authorizedAt": "…", "total": "14.28", …}}
curl -s "$FACLAB_API_URL/api/v1/invoices/812/ride" -H "Authorization: Bearer $TOKEN" -o factura.pdf
curl -s "$FACLAB_API_URL/api/v1/invoices/812/xml" -H "Authorization: Bearer $TOKEN" -o factura.xml
```

El RIDE es el PDF que se entrega al comprador. El XML autorizado es el comprobante legal. Guarda los
dos o enlaza a ellos desde la cuenta de tu cliente.

Los receptores de ejemplo, [receptor_webhooks.py](examples/python/receptor_webhooks.py) y
[receptor-webhooks.mjs](examples/javascript/receptor-webhooks.mjs), hacen los tres pasos y guardan
el RIDE en `./facturas/<clave de acceso>.pdf`.

## 4. `invoice.rejected`

Trae lo mismo más `reason`, los mensajes del SRI. Un rechazo casi siempre viene de los datos de la
empresa o del comprador, por ejemplo una identificación inválida. Tu sistema no puede reenviar la
factura: avisa a la empresa, que la corrige y la reenvía desde Faclab. Cuando se autorice, llega
`invoice.authorized` de la misma venta.

## 5. Notas de crédito

Una devolución de una venta facturada genera una **nota de crédito**. Cuando el SRI la autoriza llega
`credit_note.authorized` con `creditNoteId`, `documentId`, `number`, `accessCode`, `invoiceId` y
`saleId`. Con `documentId`, `GET /api/v1/invoices/{documentId}` y sus `/xml` y `/ride` la descargan
como a una factura.

## 6. Si algo se pierde

- Si tu receptor no responde 2xx, Faclab reintenta durante unos tres días (ver **Webhooks**). Lo que
  falló se reenvía desde el historial de entregas del webhook, en la aplicación o con
  `POST …/deliveries/{deliveryId}/retry`.
- Para conciliar, `GET /api/v1/sales?updatedSince=…` trae las ventas cambiadas con su
  `invoiceStatus` e `invoiceId`, y `GET /api/v1/invoices?saleId={id}` los comprobantes de una venta.
