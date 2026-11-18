# Recibir eventos por webhook

En lugar de consultar la API cada pocos segundos, tu sistema registra una URL y Faclab le envía un
`POST` firmado cada vez que pasa algo que le interesa: una venta confirmada, una factura autorizada,
un cambio de stock. Diseño en [PUBLIC_API.md §7](../architecture/PUBLIC_API.md) y
[ADR-0009](../architecture/ADR/0009-webhooks-firmados.md).

## 1. Registrar un endpoint

Con un token que tenga el scope `webhooks:manage`:

```bash
curl -s https://api.<dominio>/api/v1/webhook-endpoints \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://tienda.example/webhooks/faclab",
       "eventTypes": ["sale.confirmed", "invoice.authorized", "stock.changed"],
       "excludeOwnChanges": true}'
```

- La URL tiene que ser **HTTPS** y apuntar a una dirección pública. Se rechazan con
  `WEBHOOK_URL_NOT_ALLOWED` (422) las URLs `http`, con usuario o contraseña, `localhost` y las que
  resuelven a una IP privada, local, link-local o reservada. Faclab vuelve a resolver el nombre antes
  de cada envío y se conecta a la dirección que comprobó.
- Cada tipo de evento necesita que tu cliente tenga el scope de lectura de su recurso
  (`INSUFFICIENT_SCOPE`, 403, si no lo tiene). Si tu cliente está limitado a algunas sucursales, solo
  recibes los eventos de esas sucursales. Si le quitan un scope o una sucursal, deja de recibir esos
  eventos desde ese momento.
- `excludeOwnChanges: true` hace que no recibas lo que causaron tus propias solicitudes. Por ejemplo,
  la venta que creaste con `POST /api/v1/sales` no vuelve como `sale.confirmed`. Sirve para evitar
  ciclos.
- Una empresa tiene como máximo 20 endpoints (`WEBHOOK_ENDPOINT_LIMIT_REACHED`, 409).

El secreto con el que se firman los mensajes se lee aparte. Guárdalo solo en tu servidor:

```bash
curl -s https://api.<dominio>/api/v1/webhook-endpoints/$ID/secret -H "Authorization: Bearer $TOKEN"
# {"data": {"secret": "whsec_…", "previousSecret": null, "previousExpiresAt": null}, "meta": {…}}
```

| Ruta | Para qué |
|---|---|
| `GET/POST /webhook-endpoints`, `GET/PUT/DELETE /webhook-endpoints/{id}` | Listar, crear, ver, reemplazar y borrar los endpoints de tu cliente |
| `POST …/{id}/disable`, `POST …/{id}/enable` | Pausar y reanudar. Lo pendiente espera mientras está desactivado |
| `GET …/{id}/secret`, `POST …/{id}/rotate-secret` | Leer el secreto y rotarlo (ver §4) |
| `POST …/{id}/test` | Enviar un evento `webhook.test` |
| `GET …/{id}/deliveries`, `POST …/{id}/deliveries/{deliveryId}/retry` | Historial de 30 días y reenvío |

## 2. El mensaje

```http
POST /webhooks/faclab HTTP/1.1
Content-Type: application/json
webhook-id: msg_2f9a…
webhook-timestamp: 1763478245
webhook-signature: v1,K5oZfzN95Z9UVu1EsfQmfVNQhnkZ2pj9o9NDN/H/pI4=

{"id":"msg_2f9a…","type":"sale.confirmed","version":1,"occurredAt":"2026-11-18T15:04:05.000Z",
 "tenantId":"8d1c…","originClientId":"fl_live_3f2a9c1b0d4e","data":{…}}
```

- `originClientId` es el `client_id` de la integración cuya solicitud causó el evento, o `null` si
  lo causó un usuario o el sistema. Con él reconoces tus propios cambios aunque no uses
  `excludeOwnChanges`.
- Cada tipo de `data` tiene su JSON Schema en [`webhooks/v1/`](webhooks/v1/):

| Tipo | Cuándo | `data` |
|---|---|---|
| `sale.confirmed` | Se confirmó una venta de cualquier canal | La venta como la muestra `GET /api/v1/sales/{id}` |
| `sale.cancelled` | Se anuló una venta | `saleId`, `number`, `branchId`, `channel`, `externalReference`, `reason` |
| `invoice.authorized` | El SRI autorizó la factura de una venta | `invoiceId`, `saleId`, `saleNumber`, `branchId`, `externalReference`. El número, la clave de acceso y la fecha de autorización están en `GET /api/v1/invoices/{invoiceId}` |
| `invoice.rejected` | El SRI rechazó la factura | Lo mismo más `reason` (los mensajes del SRI) |
| `credit_note.authorized` | El SRI autorizó una nota de crédito | `creditNoteId`, `documentId`, `number`, `accessCode`, `authorizedAt`, `invoiceId`, `saleId`, `refundId`, `branchId` |
| `stock.changed` | Cambió el disponible de un producto en una sucursal | `productId`, `sku`, `branchId`, `available` (en unidades base, en todas las ubicaciones de la sucursal). Se agrupa: como máximo un evento por producto y sucursal cada 30 s |
| `product.updated` | Se creó un producto o cambió algo de lo que muestra la API (precio, presentaciones…) | `productId`, `sku`, `action` (`created` o `updated`), `changedFields` |
| `webhook.test` | Lo pediste con `POST …/test` | `endpointId`, `message` |

Ignora los campos que no conozcas: se agregan sin cambiar de versión. Un cambio incompatible
publicaría `version: 2`.

## 3. Verificar la firma

La firma sigue la especificación [Standard Webhooks](https://www.standardwebhooks.com/), así que
también sirven sus bibliotecas. La clave es lo que va después de `whsec_`, decodificado de base64.
Se firma `"{webhook-id}.{webhook-timestamp}.{cuerpo}"` con HMAC-SHA256, usando el cuerpo tal como
llegó, sin volver a serializarlo.

```python
import base64, hmac, hashlib, time

SECRET = base64.b64decode("whsec_…".removeprefix("whsec_"))

def verify(secret: bytes, msg_id: str, ts: str, body: bytes, header: str) -> bool:
    if abs(time.time() - int(ts)) > 300:
        return False
    expected = base64.b64encode(
        hmac.new(secret, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    ).decode()
    return any(
        hmac.compare_digest(expected, sig.split(",", 1)[1]) for sig in header.split(" ")
    )
```

```js
import crypto from "node:crypto";

const secret = Buffer.from(process.env.FACLAB_WEBHOOK_SECRET.replace(/^whsec_/, ""), "base64");

function verify(msgId, ts, rawBody, header) {
  if (Math.abs(Date.now() / 1000 - Number(ts)) > 300) return false;
  const expected = crypto.createHmac("sha256", secret).update(`${msgId}.${ts}.`).update(rawBody).digest("base64");
  return header.split(" ").some((sig) => {
    const given = Buffer.from(sig.split(",")[1] ?? "");
    return given.length === Buffer.byteLength(expected) && crypto.timingSafeEqual(given, Buffer.from(expected));
  });
}
```

Rechaza un mensaje con más de 5 minutos de antigüedad.

## 4. Responder, reintentos y desactivación

- Responde **2xx en menos de 10 s** y procesa después. Una redirección cuenta como fallo y no se
  sigue.
- Si no respondes 2xx, el mensaje se reintenta 5 s, 5 min, 30 min, 2 h, 5 h, 10 h, 24 h y 24 h
  después: 9 intentos en unos tres días. Después queda `failed`. Todos los intentos llevan el mismo
  `webhook-id`, así que deduplica por él.
- Faclab envía a cada endpoint una entrega a la vez. Los mensajes pueden llegar desordenados: usa
  `occurredAt` y, cuando el orden importe, consulta el estado actual por la API.
- Si una entrega agota sus intentos y tu endpoint no respondió bien a ninguna desde que esa entrega
  se creó, Faclab lo desactiva (`status: disabled`, `disabledReason: failing`) y avisa por correo a
  los administradores de la empresa. Lo pendiente se conserva. Cuando arregles el receptor:
  `POST …/{id}/enable`, y reenvía las fallidas con `POST …/deliveries/{deliveryId}/retry`, que
  manda el mismo `webhook-id` con todos sus intentos de nuevo.
- **Rotación del secreto:** `POST …/{id}/rotate-secret` crea un secreto nuevo. El anterior sigue
  firmando junto a él durante `previousExpiresInHours` (24 por defecto, de 0 a 72), y en ese tiempo
  el encabezado lleva dos firmas. Cambia el secreto en tu receptor dentro de ese plazo.
