# API pública para integraciones

> Decisiones: [ADR-0008](ADR/0008-api-publica-versionada-y-credenciales-de-integracion.md) (fachada
> `/api/v1`, OAuth 2.0 *client credentials*, tokens asimétricos) y
> [ADR-0009](ADR/0009-webhooks-firmados.md) (webhooks). Se implementa en la Etapa 6, después de
> multiempresa (Etapa 2) e idempotencia (S3.1, terminada: el POS ya exige `Idempotency-Key` con el
> mecanismo que reutiliza `/api/v1`, ver `docs/pos-api-spec.md` §0.1). Las credenciales de
> integración (§3) están implementadas desde S6.2, la fachada `/api/v1` con sus límites (§4, §5, §9)
> desde S6.3, los webhooks (§7) desde S6.4 y el portal, la documentación pública y el sandbox (§10)
> desde S6.5. La guía para integradores está en [`docs/public-api/`](../public-api/README.md).

## 1. Principios

1. **Contrato propio, no el esquema de la base.** Los recursos públicos tienen modelos propios. Agregar
   una columna interna no cambia la API y renombrarla no la rompe.
2. **Escrituras por comandos de negocio.** No existe un "PATCH de tabla". Una venta se crea con el mismo
   comando que usa el POS, con las mismas validaciones de stock, caja y permisos.
3. **La empresa viene del token.** Ningún endpoint acepta `tenantId`. La sucursal se indica con
   `X-Branch-Id` o en el recurso, y se valida contra el alcance de la credencial.
4. **Reintentos seguros.** `Idempotency-Key` obligatorio en todo POST que crea documentos.
5. **Estable y documentado.** OpenAPI público, changelog, política de deprecación y ejemplos que se
   ejecutan en CI contra el sandbox.

## 2. Fuentes de verdad y qué se puede modificar

| Dato | Fuente de verdad | Lectura por API | Escritura por API |
|---|---|---|---|
| Productos, categorías, unidades, presentaciones | core | Sí | Sí (crear y actualizar; no borrar con historial) |
| Precios y listas de precios | core | Sí | Sí, con scope específico |
| Stock por sucursal | core (derivado de movimientos) | Sí | **No directo**: solo por documentos (ajuste, recepción, transferencia), con scope específico |
| Clientes | core | Sí | Sí (alta y actualización con búsqueda por identificación) |
| Ventas | core | Sí | Sí: crear y confirmar como venta de canal `api`; anular según reglas |
| Pagos | core | Sí | Sí, sobre ventas propias |
| Comprobantes (facturas, notas de crédito) | invoicing | Sí, incluidos XML autorizado y RIDE | No: se generan a partir de ventas y devoluciones |
| Sucursales, puntos de emisión | core | Sí | No (se administran en la aplicación) |
| Usuarios, roles, perfil fiscal, certificados | core / invoicing | No | No |

## 3. Autenticación y autorización

> **Implementado en S6.2** (2026-11-17). Detalle operativo en `docs/auth-spec.md` (sección
> *Integration clients*). Lo que sigue describe lo implementado; las diferencias con el diseño inicial
> se indican en cada punto.

### 3.1 Tipos de credencial

| Credencial | Uso | Emisión | Duración |
|---|---|---|---|
| Sesión de usuario | Frontend | Login + selección de empresa | Access 15 min; refresh rotativo |
| Cliente de integración | Sistemas de terceros, del lado servidor | `POST /api/oauth/token` con `grant_type=client_credentials` | Access 15 min; sin refresh |

Las aplicaciones móviles o de navegador de terceros **no** reciben secretos de cliente. Si en el futuro
se necesita que actúen en nombre de un usuario, se agrega *authorization code* con PKCE (fuera del
alcance inicial).

### 3.2 Cliente de integración

- Lo crea un administrador de la empresa con `POST /api/admin/integrations` (permiso
  `integration:manage`, solo ADMIN; desde S6.5 también en el portal de faclab-web,
  **Configuración → Integraciones**), que elige:
  - Nombre del cliente.
  - Scopes.
  - Sucursales permitidas (opcional; ninguna = todas).
  - IPs o redes permitidas en CIDR (opcional; ninguna = cualquiera).
- **Entorno:** lo fija el despliegue (`INTEGRATION_ENVIRONMENT`: `production` en producción, `sandbox`
  en los demás), no el administrador. El `client_id` lo dice (`fl_live_…` o `fl_test_…`) y el
  endpoint de token rechaza un cliente de otro entorno, así las credenciales de una base de producción
  restaurada en staging no sirven allí.
- El secreto (256 bits aleatorios) se muestra **una sola vez**, al crear el cliente o un secreto nuevo.
  Se guarda su **SHA-256** y sus primeros seis caracteres, que lo identifican en los listados. Cambio
  respecto del diseño inicial (argon2 o bcrypt): un hash lento protege contraseñas que una persona
  elige y que se adivinan con diccionario; un secreto aleatorio de 256 bits no se adivina con ninguno
  de los dos, y un hash rápido evita que el endpoint de token gaste CPU en cada intento (es la
  práctica de las claves de API de GitHub o Stripe). La comparación es en tiempo constante.
- **Rotación:** hasta dos secretos activos a la vez (`POST …/{id}/secrets`); el anterior se revoca
  manualmente o expira en N días (`previousExpiresInDays`).
- **Revocación:** revocar el cliente o uno de sus secretos invalida sus tokens al consultar el estado
  del cliente, que cada proceso cachea `INTEGRATION_STATUS_CACHE_SECONDS` (30 s; como máximo 60).
  Quitarle un scope o una sucursal también rige en ese plazo: el token vale por la intersección.
- **Registro de uso:** por día, tokens obtenidos y rechazados, solicitudes, errores (4xx y 5xx) y la
  última IP de origen, sin una fila por solicitud (`GET …/{id}/usage`); el cliente guarda su último
  uso. Cada escritura queda en la bitácora de auditoría (S3.5) con el cliente como actor
  (`actor_integration_id` y su nombre, sin usuario).
- **Plan:** un scope que el plan de la empresa no incluye se rechaza (`SCOPE_NOT_IN_PLAN`). Desde S8.4
  el puerto `IntegrationPlan` lo implementa el módulo de suscripciones: un plan con la API pública da
  todos los scopes y uno sin ella, ninguno. Un cliente más allá del plan responde `PLAN_LIMIT_REACHED`
  (409), y una suscripción que no está activa deja la API en solo lectura (`SUBSCRIPTION_READ_ONLY`,
  403).

### 3.3 Token

```json
{
  "iss": "faclab-core",
  "aud": "faclab-core",
  "sub": "client:fl_live_3f2a9c1b0d4e",
  "azp": "fl_live_3f2a9c1b0d4e",
  "tid": "8d1c…",
  "scope": "invoices:read products:read sales:write stock:read",
  "bids": [12, 15],
  "cred": 41,
  "typ": "access",
  "iat": 1760000000,
  "exp": 1760000900
}
```

Lo firma el core con su clave Ed25519 (el `kid` va en el encabezado) y se valida con
`/.well-known/jwks.json` (S6.1). `bids` solo cuando el cliente está limitado a algunas sucursales;
`cred` es el secreto con el que se obtuvo. No lleva `role` ni `perms`. Desde S6.3 `aud` es
`["faclab-core", "faclab-invoicing"]`, como el access token de un usuario: `/api/v1/invoices` de
facturación valida el scope `invoices:read` y sus rutas internas rechazan el token
(`INTEGRATION_NOT_ALLOWED`). Facturación no consulta el estado del cliente: allí un token revocado
vale hasta que vence (15 minutos como máximo).

En el core, las rutas internas (`/api/admin`, `/api/pos`, `/api/auth`) responden 403
`INTEGRATION_NOT_ALLOWED` a un token de integración; las rutas que lo aceptan declaran el scope con
`require_scope` (403 `INSUFFICIENT_SCOPE` sin él). Un token revocado, de un secreto revocado o desde una
IP no permitida responde 401 `INVALID_TOKEN`.

El endpoint de token sigue RFC 6749 en sus respuestas, no el envelope de la API, para que sirva
cualquier biblioteca OAuth: errores `{"error", "error_description"}` con 400 (`invalid_request`,
`unsupported_grant_type`, `invalid_scope`), 401 (`invalid_client`, sin decir si el secreto, el cliente
o la IP es lo que falla) o 503 (`temporarily_unavailable`, con `INTEGRATIONS_ENABLED=false`). Las
credenciales van con HTTP Basic o en el formulario, nunca de las dos formas.

### 3.4 Scopes iniciales

| Scope | Permite |
|---|---|
| `products:read` / `products:write` | Catálogo, categorías, unidades, presentaciones |
| `prices:read` / `prices:write` | Listas de precios |
| `stock:read` | Stock por sucursal y bodega |
| `inventory:write` | Documentos de inventario (ajuste, transferencia) |
| `customers:read` / `customers:write` | Clientes |
| `sales:read` / `sales:write` | Ventas y pagos |
| `invoices:read` | Comprobantes, XML y RIDE |
| `webhooks:manage` | Suscripciones de webhooks |

Cada scope se traduce a los `Permission` existentes (`PERMISSIONS_BY_SCOPE` en
`src/auth/domain/scopes.py`, con una prueba que fija la tabla completa):

| Scope | Permisos |
|---|---|
| `products:read` | `product:read` |
| `products:write` | `product:write`, `category:write`, `uom:write` |
| `prices:read` / `prices:write` | `product:read` / `product:write` (las listas de precios usan los permisos de producto) |
| `stock:read` | `stock:read` |
| `inventory:write` | `adjustment:write`, `transfer:write` |
| `customers:read` / `customers:write` | `customer:read` / `customer:write` |
| `sales:read` | `sale:read` |
| `sales:write` | `sale:write`, `sale:cancel` |
| `invoices:read` | `sale:read` |
| `webhooks:manage` | ninguno: las rutas `/api/v1/webhook-endpoints` exigen el scope directamente (S6.4) |

Ningún scope da permisos de administración (`user:manage`, `audit:read`, `organization:write`,
`import:write`, `integration:manage`) ni de operación de caja (`pos:operate`, `refund:approve`). Una
integración nunca puede tener más scopes que el plan de la empresa permite.

## 4. Convenciones

| Tema | Convención |
|---|---|
| URL base | `https://api.<dominio>/api/v1` (producción), `https://sandbox.<dominio>/api/v1` |
| Recursos | Sustantivos en plural, kebab-case: `/products`, `/price-lists`, `/webhook-endpoints` |
| Formato | JSON con camelCase (igual que la API interna) |
| Fechas | ISO 8601 en UTC con `Z` |
| Dinero | **String decimal** (`"12.50"`: al menos dos decimales, hasta seis en precios de línea), nunca número de punto flotante; la moneda es USD. En las solicitudes se acepta string o entero; un número JSON con decimales se rechaza (422) |
| Cantidades | String decimal sin ceros sobrantes (`"2.5"`, `"3"`), con los decimales que admite la unidad |
| Paginación | `limit` (1 a 200, 50 por defecto) y `offset`, siempre en orden estable: el id desempata en la misma dirección. Para sincronizar, `updatedSince` (inclusivo) y, sin `sort`, orden por `updatedAt, id`. Paginación por cursor si el volumen lo exige |
| Filtros | Parámetros explícitos por recurso (`sku`, `barcode`, `branchId`, `status`, `from`, `to`) |
| Orden | `sort=campo` o `sort=-campo` sobre una lista blanca por recurso (otro campo: 422 `VALIDATION_ERROR` con `field: "sort"`) |
| Envelope | `{data, meta}` y `{errors:[{code, message, field?}], meta}`, el mismo que la API interna (`src/shared/infra/validators.py`) |
| Códigos de error | Catálogo público estable (`PUBLIC_ERROR_CODES` en `src/public_api/infra/errors.py`, documentado en `docs/public-api/errores.md`): un código interno fuera de él se traduce al genérico de su estado (`BUSINESS_RULE_VIOLATION` 400, `CONFLICT` 409, `VALIDATION_ERROR` 422…) y el original queda en el log |
| Respuestas | Cada campo del esquema se envía siempre (`null` sin valor): el OpenAPI los marca requeridos, así quitar uno es un cambio incompatible. Ningún campo interno sale: los esquemas públicos son propios (`src/public_api/infra/schemas/`) |
| Idempotencia | `Idempotency-Key` (UUID) en **todo POST** de `/api/v1`; misma clave y mismo cuerpo devuelven la misma respuesta durante 24 h (con `Idempotent-Replayed: true`); misma clave con otro cuerpo devuelve 422 `IDEMPOTENCY_KEY_REUSED`; una solicitud con la clave en curso espera su respuesta o, tras 10 s, 409 `IDEMPOTENCY_IN_PROGRESS`; los errores no se guardan. Implementado en el POS en S3.1 (`src/shared/infra/idempotency/`): la v1 aplica la misma dependencia a sus rutas |
| Correlación | `X-Request-Id` en la respuesta, que aparece en el soporte y en los logs |
| Límites | 429 `RATE_LIMITED` con `Retry-After`; encabezados `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` y `RateLimit-Policy` en cada respuesta (§9) |
| Apagado | `PUBLIC_API_ENABLED=false` responde 503 `PUBLIC_API_DISABLED` en todas las rutas (la vuelta atrás) |

## 5. Catálogo inicial de endpoints

| Método y ruta | Scope | Servicio | Notas |
|---|---|---|---|
| `POST /api/oauth/token` | — | core | *Client credentials* |
| `GET /.well-known/jwks.json` | — | core | Claves públicas |
| `GET /api/v1/branches` | cualquiera | core | Sucursales activas permitidas para el cliente, con sus puntos de emisión y ubicaciones activos (lo que nombra una venta) |
| `GET /api/v1/products` | `products:read` | core | Filtros `sku`, `barcode` (de cualquier presentación), `search`, `updatedSince`; `sort`: `id`, `name`, `sku`, `createdAt`, `updatedAt`. Cambiar una presentación actualiza su producto |
| `GET /api/v1/products/{id}` | `products:read` | core | Incluye presentaciones con su precio de venta. El costo de compra no es público |
| `POST /api/v1/products` | `products:write` | core | Idempotente; crea la presentación base |
| `PUT /api/v1/products/{id}` | `products:write` | core | Reemplazo de campos editables; costo y umbrales de stock quedan como están |
| `GET /api/v1/price-lists`, `GET /api/v1/price-lists/{id}/items` | `prices:read` | core | Listas (con la general) e ítems por producto, presentación y escala |
| `GET /api/v1/stock` | `stock:read` | core | Filas por producto y ubicación de las bodegas de una sucursal; `branchId` obligatorio salvo que el cliente opere en una sola sucursal (`BRANCH_REQUIRED`); `productId`, `updatedSince` |
| `GET /api/v1/customers` | `customers:read` | core | Filtro `identification` |
| `GET /api/v1/customers/{id}` | `customers:read` | core | Agregado en S6.3 |
| `POST /api/v1/customers` | `customers:write` | core | Si existe la identificación, 409 `CUSTOMER_ALREADY_EXISTS` con el id en `existingId`; idempotente |
| `PUT /api/v1/customers/{id}` | `customers:write` | core | El crédito (cupo, plazo) no es público y queda como está |
| `POST /api/v1/sales` | `sales:write` | core | Crea y confirma una venta de canal `api` en la sucursal de `X-Branch-Id`, en el punto de emisión `emissionPointId` y con el stock de la ubicación `locationId`; pagada en línea (`CREDIT_CARD`, `DEBIT_CARD`, `TRANSFER`, `OTHER`, por el total exacto); valida stock; idempotente |
| `GET /api/v1/sales`, `GET /api/v1/sales/{id}` | `sales:read` | core | Ventas de todos los canales de las sucursales del cliente, con ítems, pagos y estado de facturación; filtros `branchId`, `status`, `invoiceStatus`, `channel`, `externalReference`, `from`, `to`, `updatedSince` |
| `POST /api/v1/sales/{id}/cancel` | `sales:write` | core | Solo ventas del mismo cliente (`PERMISSION_DENIED` para las demás); según reglas: antes de facturar (`INVOICE_IN_PROGRESS`) o con nota de crédito (`CREDIT_NOTE_REQUIRED`) |
| `GET /api/v1/invoices` | `invoices:read` | invoicing | Facturas y notas de crédito (`documentType`) de las sucursales del cliente; filtros `saleId`, `status` (`PROCESSING`, `AUTHORIZED`, `REJECTED`), `documentType`, `from`, `to`, `branchId`, `updatedSince`; `sort`: `createdAt`, `updatedAt`, `id` |
| `GET /api/v1/invoices/{id}` | `invoices:read` | invoicing | Número, clave de acceso, autorización, motivo del rechazo, total |
| `GET /api/v1/invoices/{id}/xml`, `/ride` | `invoices:read` | invoicing | XML autorizado y PDF. Ya existen en la API interna (S4.1 y S4.4): `GET /api/invoices/{id}/authorized-xml` y `GET /api/invoices/{id}/ride`, adjuntos con la clave de acceso como nombre, 404 hasta que la factura esté autorizada; v1 los expone con otro prefijo y el scope |
| `GET/POST /api/v1/webhook-endpoints`, `GET/PUT/DELETE …/{id}` | `webhooks:manage` | core | Solo los endpoints del cliente; idempotente; URL HTTPS hacia una dirección pública (`WEBHOOK_URL_NOT_ALLOWED`); cada evento necesita el scope de lectura de su recurso; 20 por empresa |
| `POST …/{id}/enable`, `/disable` | `webhooks:manage` | core | Agregados en S6.4: reanudar y pausar (lo pendiente espera) |
| `GET …/{id}/secret`, `POST …/{id}/rotate-secret` | `webhooks:manage` | core | Agregados en S6.4: el secreto (`whsec_…`) y su rotación, con el anterior firmando 24 h más |
| `POST /api/v1/webhook-endpoints/{id}/test` | `webhooks:manage` | core | Envía un evento `webhook.test` |
| `GET /api/v1/webhook-endpoints/{id}/deliveries` | `webhooks:manage` | core | Últimos 30 días; reenvío con `POST .../{deliveryId}/retry` |

El administrador de la empresa gestiona todos los endpoints, de la empresa y de sus clientes, en
`/api/admin/webhook-endpoints` (permiso `integration:manage`), con las mismas rutas.

Caddy enruta `/api/v1/invoices*` a invoicing y el resto a core, bajo un solo dominio y un solo token
(S8.1). Cada documento de facturación guarda la sucursal de su venta (`branch_id` de
`sales.confirmed` v3 y `credit_notes.requested` v2, desde S6.3): los recibidos antes no la tienen y
solo los ve un cliente sin límite de sucursales.

**Pagos.** La venta de la API llega pagada en línea: no entra en ninguna caja ni queda a crédito
(`CASH` y `CREDIT` no se aceptan). `POST /api/v1/sales/{id}/payments`, previsto en el diseño
inicial, queda fuera de v1 (decisión de S6.3): se agregará como cambio compatible si hacen falta
ventas a crédito o pagos posteriores.

El RIDE se genera desde el XML autorizado la primera vez que se pide o cuando la factura se entrega
al comprador, y se guarda junto al XML (S4.4). El reenvío por correo (`POST /api/invoices/{id}/email`)
queda en la API interna: un cliente de integración no elige a quién se envía.

## 6. Ejemplos de contrato

Obtener token (`curl`):

```bash
curl -s https://api.faclab.ec/api/oauth/token \
  -u "$FACLAB_CLIENT_ID:$FACLAB_CLIENT_SECRET" \
  -d grant_type=client_credentials \
  -d scope="stock:read sales:write"
```

```json
{"access_token": "eyJ…", "token_type": "Bearer", "expires_in": 900, "scope": "stock:read sales:write"}
```

Consultar stock de una sucursal (Python):

```python
import httpx

token = obtener_token()  # cachear hasta expires_in
resp = httpx.get(
    "https://api.faclab.ec/api/v1/stock",
    params={"branchId": 12, "updatedSince": "2026-10-14T00:00:00Z", "limit": 200},
    headers={"Authorization": f"Bearer {token}"},
)
resp.raise_for_status()
for row in resp.json()["data"]:
    print(row["productId"], row["sku"], row["available"])
```

Crear una venta idempotente (JavaScript):

```js
const res = await fetch("https://api.faclab.ec/api/v1/sales", {
  method: "POST",
  headers: {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
    "Idempotency-Key": crypto.randomUUID(), // guardar y reutilizar en cada reintento del mismo pedido
    "X-Branch-Id": "12",
  },
  body: JSON.stringify({
    emissionPointId: 31, // GET /api/v1/branches
    locationId: 44,
    externalReference: "WEB-100234",
    customer: { identification: "1712345678" }, // o { id }; sin customer, consumidor final
    items: [{ productId: 501, quantity: "3" }], // al precio de sus listas
    payments: [{ method: "TRANSFER", amount: "14.28", reference: "pasarela-7f3a" }],
  }),
});
if (res.status === 409) {
  /* conflicto de negocio: ver errors[0].code */
}
const { data } = await res.json(); // { id, number, status: "CONFIRMED", invoiceStatus: "PENDING", ... }
```

Los montos del ejemplo son ilustrativos. El total con IVA lo calcula el core con las reglas existentes
(`src/sales/domain/services.py`).

## 7. Webhooks

> **Implementado en S6.4** (2026-11-18). Guía para integradores en
> [`docs/public-api/webhooks.md`](../public-api/webhooks.md); contratos en
> [`docs/public-api/webhooks/v1/`](../public-api/webhooks/v1/).

### 7.1 Eventos iniciales

| Tipo | Cuándo | Datos principales |
|---|---|---|
| `sale.confirmed` | Venta confirmada (cualquier canal) | La venta como `GET /api/v1/sales/{id}`: número, sucursal, totales, ítems, pagos, canal, `externalReference` |
| `sale.cancelled` | Venta anulada | id, número, sucursal, canal, `externalReference`, motivo |
| `invoice.authorized` | Factura autorizada | id de la factura, venta, número de la venta, sucursal |
| `invoice.rejected` | Factura rechazada | Lo mismo más el motivo (los mensajes del SRI unidos con ` >> `) |
| `credit_note.authorized` | Nota de crédito autorizada | id, documento, número, clave de acceso, fecha de autorización, factura de referencia, venta, devolución |
| `stock.changed` | Cambió el disponible de un producto en una sucursal (agrupado cada 30 s) | producto, SKU, sucursal, disponible |
| `product.updated` | Alta o cambio de un campo público del producto, su precio o sus presentaciones | id, sku, `action` (`created`/`updated`), campos cambiados |
| `webhook.test` | Pedido con `POST …/test` | endpoint, mensaje |

Diferencias con el diseño inicial:

- `invoice.authorized` no lleva número, clave de acceso ni fecha de autorización, e
  `invoice.rejected` lleva el texto del SRI en lugar de sus códigos: el mensaje `invoices` que
  faclab-invoicing publica al core no los trae. El integrador los lee en
  `GET /api/v1/invoices/{id}`. Agregarlos es un cambio compatible pendiente (ampliar `invoices` v1
  en los dos servicios).
- `product.updated` no se emite cuando solo cambian campos internos (costo, umbrales de stock). Las
  listas de precios no lo emiten todavía.

### 7.2 Entrega

```http
POST /webhooks/faclab HTTP/1.1
Content-Type: application/json
webhook-id: msg_2f9a…
webhook-timestamp: 1760461445
webhook-signature: v1,K5oZfzN95Z9UVu1EsfQmfVNQhnkZ2pj9o9NDN/H/pI4=

{"id":"msg_2f9a…","type":"invoice.authorized","version":1,
 "occurredAt":"2026-10-14T15:04:05.000Z","tenantId":"8d1c…","originClientId":null,"data":{…}}
```

- La firma sigue Standard Webhooks: HMAC-SHA256 en base64 sobre
  `"{webhook-id}.{webhook-timestamp}.{cuerpo}"`. La clave es el secreto `whsec_<base64>` decodificado
  después del prefijo. Se rechazan los mensajes con más de 5 minutos de antigüedad.
- **Secretos:** cada endpoint tiene el suyo, cifrado en la base con la clave maestra del entorno
  (`SECRET_ENCRYPTION_KEYS`, Fernet; la primera cifra y cualquiera descifra, así que la clave maestra
  también rota). Se lee con `GET …/{id}/secret`. Las respuestas de crear y rotar no lo traen, así la
  tabla de idempotencia nunca lo guarda. En una rotación el anterior firma junto al nuevo durante
  24 h (configurable de 0 a 72), con dos firmas en el encabezado.
- **Encolado:** cada evento de dominio escribe, en su misma transacción, un `webhook_messages` (el
  cuerpo completo, el mismo en cada intento) y una `webhook_deliveries` por endpoint que lo quiere.
  Un endpoint de un cliente recibe solo lo que el cliente puede leer en ese momento (scopes y
  sucursales). `stock.changed` se agrupa en un búfer de solo inserción que el worker reúne cada
  `WEBHOOK_STOCK_BATCH_SECONDS`.
- **Envío** (el worker, `src/webhooks/infra/dispatcher.py`):
  - una entrega a la vez por endpoint, con un *lease* (`locked_until`), y hasta
    `WEBHOOK_CONCURRENCY` en paralelo: un receptor lento solo frena su propia cola;
  - timeout total de 10 s; las redirecciones no se siguen;
  - Faclab resuelve el nombre del host antes de cada intento, valida cada dirección y se conecta a
    la dirección validada, con verificación TLS contra el nombre del host.
- Hay que responder 2xx en menos de 10 s; el procesamiento pesado se hace después.
- Reintentos 5 s, 5 min, 30 min, 2 h, 5 h, 10 h, 24 h y 24 h después: 9 intentos en unos tres días.
  Si una entrega los agota y el endpoint no respondió bien a ninguna desde que esa entrega se creó,
  el endpoint se desactiva (`disabledReason: failing`). La desactivación se audita, queda en el log
  como ERROR y se avisa por correo a los administradores de la empresa. Lo pendiente se conserva:
  al reactivarlo sigue saliendo, y las entregas fallidas se reenvían a mano.
- El receptor deduplica por `webhook-id`. Los eventos pueden llegar desordenados: se usa
  `occurredAt` y el estado actual consultado por API cuando el orden importa.
- **Prevención de ciclos:** el mensaje lleva `originClientId`, el `azp` del cliente cuya solicitud
  lo causó (o `null`). Un endpoint de ese cliente con `excludeOwnChanges` no lo recibe. Además,
  `externalReference` permite que el sistema externo reconozca sus propios registros.
- **Seguridad:** solo HTTPS hacia direcciones globales. Se rechazan las privadas, loopback,
  link-local (169.254.169.254), compartidas (100.64/10), multicast, reservadas y de documentación,
  también dentro de una IPv6 (IPv4 mapeada, 6to4, Teredo), al registrar y en cada envío.
  `WEBHOOK_ALLOW_PRIVATE_URLS` las permite solo en local.
- **Operación:** historial de 30 días (`WEBHOOK_RETENTION_DAYS`, purgado por el worker), evento de
  prueba y reenvío. `WEBHOOK_DELIVERY_ENABLED=false` pausa el envío y conserva lo pendiente;
  `WEBHOOKS_ENABLED=false` además deja de encolar y apaga las rutas (503 `WEBHOOKS_DISABLED`).
  Métrica `faclab.webhooks.deliveries` por resultado.

Verificación (Python):

```python
import base64, hmac, hashlib, time

secret = base64.b64decode("whsec_…".removeprefix("whsec_"))

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

Las pruebas usan esta función tal cual: `tests/webhook_receiver.py` la usa para verificar cada
mensaje que recibe el receptor HTTPS local.

## 8. Versionado y compatibilidad

- **Compatible (sin cambiar de versión):** agregar endpoints, campos opcionales en solicitudes, campos
  en respuestas, valores nuevos de enums documentados como extensibles, eventos nuevos.
- **Incompatible:** quitar o renombrar campos, cambiar tipos, volver obligatorio un campo, cambiar
  semántica. Se publica `/api/v2` (o `version: 2` en el webhook) y v1 se mantiene **al menos 6 meses**,
  con encabezados `Deprecation` y `Sunset` y aviso por correo a las empresas con integraciones activas.
- Los integradores deben ignorar campos desconocidos. Se documenta y se prueba en el SDK de ejemplo.
- El changelog público vive junto al OpenAPI. Cada versión del OpenAPI público se guarda en el
  repositorio y el CI compara la nueva con la anterior para detectar cambios incompatibles
  (por ejemplo, con `oasdiff`).

## 9. Límites de solicitudes y protección

- Por IP en Caddy (protección básica).
- Por cliente y por empresa en la aplicación (S6.3): 600 solicitudes por minuto por cliente con
  ráfagas de 50 y 1200 por minuto por empresa con ráfagas de 100 (`PUBLIC_API_RATE_LIMIT_*` y
  `PUBLIC_API_TENANT_RATE_LIMIT_*`). Son valores iniciales; S8.4 dejó los planes sin límites de
  solicitudes propios, que quedan pendientes en el ROADMAP. Cada
  servicio cuenta las solicitudes a sus rutas: core las de su `/api/v1`, facturación las de
  `/api/v1/invoices`.
- Algoritmo GCRA: cada clave guarda un solo número, el momento en que su balde vuelve a estar vacío.
  `RateLimit-Limit` es la ráfaga, `RateLimit-Remaining` lo que queda de ella, `RateLimit-Reset` los
  segundos hasta que se llena otra vez y `RateLimit-Policy` la ráfaga y su ventana (`50;w=5`). Al
  exceder: 429 `RATE_LIMITED` con `Retry-After`.
- Almacén de contadores: **decisión D-6 resuelta en S6.3: PostgreSQL**. Tabla de plataforma
  `api_rate_limits` (sin RLS) con un `INSERT … ON CONFLICT … DO UPDATE … WHERE … RETURNING` por
  clave, atómico y compartido entre procesos, en una transacción propia antes de la ruta; el worker
  purga las claves vencidas. Detrás del puerto `RateLimiter`, así pasar a Redis no toca las rutas. Si
  el almacén falla, la solicitud sigue (se registra en el log). Sin infraestructura nueva para el
  piloto; Redis cuando el volumen lo pida.
- `POST /api/oauth/token` no tiene límite por cliente todavía: solo el del proxy por IP.
- Tamaño máximo de cuerpo de 1 MB y timeouts de lectura en Caddy.
- Endpoints de exportación masiva fuera del alcance inicial; se usa paginación con `updatedSince`.

## 10. Experiencia de integración

> **Implementado en S6.5** (2026-11-19), salvo el sandbox desplegado (S8.1, D-9) y la
> configuración de facturación de sus empresas (pendiente).

- **Documentación:** `/docs/public` (Scalar), pública también donde `DOCS_ENABLED` está apagado
  (`PUBLIC_DOCS_ENABLED`). Una página con las guías como introducción, la referencia del OpenAPI
  público del core más la copia fijada del de facturación (`docs/public-api/invoicing/`) y los
  eventos de webhook como `webhooks` de OpenAPI 3.1 (`src/public_api/infra/docs.py`). El contrato
  sigue siendo `/openapi/public.json`, que esa página no cambia. Guías: primeros pasos,
  autenticación, sincronizar catálogo y stock, ventas desde un ecommerce, facturas por webhook,
  webhooks, errores y límites. Los ejemplos y los JSON Schema se sirven en `/docs/public/files/`.
- **Ejemplos** en `curl`, Python y JavaScript (`docs/public-api/examples/`), con su
  `run-all.sh`. El job `examples` del CI los corre en cada PR contra un core de sandbox levantado en
  el mismo job (PostgreSQL, API y worker, sin Kafka): token, catálogo, stock, venta con reintento y
  anulación, y webhooks firmados recibidos en el runner. Las descargas de facturas no corren allí.
  Correrlos contra el sandbox desplegado queda para S8.1.
- **Sandbox:** un despliegue aparte (`INTEGRATION_ENVIRONMENT=sandbox`) con una empresa de prueba
  por integrador y datos ficticios: `make sandbox` (`scripts/sandbox.py`, se niega fuera del
  sandbox). Facturación en el ambiente de pruebas del SRI configurando la empresa en
  faclab-invoicing (`docs/sandbox.md`). Las credenciales tienen el prefijo `fl_test_` y apuntan a
  `https://sandbox.<dominio>`.
- **SDK oficial:** solo cuando haya demanda de varios integradores. Mientras tanto, OpenAPI permite
  generar clientes, y los clientes mínimos de los ejemplos (`faclab.py`, `faclab.mjs`) sirven de
  base.
- **Portal en la aplicación** (faclab-web, `integration:manage`): clientes de integración (crear,
  editar, rotar y revocar secretos, revocar), scopes, sucursales, redes, uso de 30 días, webhooks
  con su secreto, prueba, historial de entregas y reenvío.
