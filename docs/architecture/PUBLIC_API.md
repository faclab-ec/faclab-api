# API pública para integraciones

> Decisiones: [ADR-0008](ADR/0008-api-publica-versionada-y-credenciales-de-integracion.md) (fachada
> `/api/v1`, OAuth 2.0 *client credentials*, tokens asimétricos) y
> [ADR-0009](ADR/0009-webhooks-firmados.md) (webhooks). Hoy solo existen las rutas internas del
> frontend (G-72). Se implementa en la Etapa 6, después de multiempresa (Etapa 2) e idempotencia (S3.1,
> terminada: el POS ya exige `Idempotency-Key` con el mecanismo que reutilizará `/api/v1`, ver
> `docs/pos-api-spec.md` §0.1).

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

### 3.1 Tipos de credencial

| Credencial | Uso | Emisión | Duración |
|---|---|---|---|
| Sesión de usuario | Frontend | Login + selección de empresa | Access 15 min; refresh rotativo |
| Cliente de integración | Sistemas de terceros, del lado servidor | `POST /api/oauth/token` con `grant_type=client_credentials` | Access 15 min; sin refresh |

Las aplicaciones móviles o de navegador de terceros **no** reciben secretos de cliente. Si en el futuro
se necesita que actúen en nombre de un usuario, se agrega *authorization code* con PKCE (fuera del
alcance inicial).

### 3.2 Cliente de integración

- Lo crea un administrador de la empresa en el portal (S6.5), que elige:
  - Nombre del cliente.
  - Scopes.
  - Sucursales permitidas (opcional).
  - IPs permitidas (opcional).
  - Entorno: sandbox o producción.
- El secreto se muestra **una sola vez**. Se guarda como hash (argon2 o bcrypt) y se identifica por un
  prefijo visible (`fl_live_abc…`, `fl_test_abc…`).
- **Rotación:** se pueden tener dos secretos activos a la vez; el anterior se revoca manualmente o
  expira en N días.
- **Revocación inmediata:** los tokens emitidos dejan de valer al consultar el estado del cliente. Se
  cachea 60 s como máximo.
- **Registro de uso:** última vez usado, solicitudes por día, errores, y la IP de origen agregada sin
  guardar el detalle de cada IP. Cada escritura queda en la bitácora de auditoría (S3.5) con
  `actor = cliente de integración`.

### 3.3 Token

```json
{
  "iss": "https://api.faclab.ec",
  "sub": "client:3f2a…",
  "azp": "fl_live_3f2a",
  "tid": "8d1c…",
  "scope": "products:read stock:read sales:write invoices:read",
  "bids": [12, 15],
  "typ": "access",
  "exp": 1760000000,
  "kid": "2026-10"
}
```

Lo firma el core con una clave asimétrica y facturación lo valida con `/.well-known/jwks.json` (S6.1).

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

Cada scope se traduce a los `Permission` existentes (`src/auth/domain/permissions.py`). Una integración
nunca puede tener más permisos que el plan de la empresa permite.

## 4. Convenciones

| Tema | Convención |
|---|---|
| URL base | `https://api.<dominio>/api/v1` (producción), `https://sandbox.<dominio>/api/v1` |
| Recursos | Sustantivos en plural, kebab-case: `/products`, `/price-lists`, `/webhook-endpoints` |
| Formato | JSON con camelCase (igual que la API interna) |
| Fechas | ISO 8601 en UTC con `Z` |
| Dinero | **String decimal** (`"12.50"`), nunca número de punto flotante; la moneda es USD |
| Cantidades | String decimal (`"2.500"`) a partir de S5.1 |
| Paginación | `limit` (máx. 200) y `offset`, con orden estable obligatorio. Para sincronización, `updatedSince` + orden por `updatedAt, id`. Paginación por cursor si el volumen lo exige |
| Filtros | Parámetros explícitos por recurso (`sku`, `barcode`, `branchId`, `status`, `from`, `to`) |
| Orden | `sort=campo` o `sort=-campo` sobre una lista blanca por recurso |
| Envelope | `{data, meta}` y `{errors:[{code, message, field?}], meta}`, el mismo que la API interna (`src/shared/infra/validators.py`) |
| Códigos de error | Catálogo público estable (`NOT_FOUND`, `VALIDATION_ERROR`, `INSUFFICIENT_STOCK`, `IDEMPOTENCY_KEY_REUSED`, `RATE_LIMITED`…); nunca textos internos |
| Idempotencia | `Idempotency-Key` (UUID) en POST de creación; misma clave y mismo cuerpo devuelven la misma respuesta durante 24 h (con `Idempotent-Replayed: true`); misma clave con otro cuerpo devuelve 422 `IDEMPOTENCY_KEY_REUSED`; una solicitud con la clave en curso espera su respuesta o, tras 10 s, 409 `IDEMPOTENCY_IN_PROGRESS`; los errores no se guardan. Implementado en el POS en S3.1 (`src/shared/infra/idempotency/`): la v1 aplica la misma dependencia a sus rutas |
| Correlación | `X-Request-Id` en la respuesta, que aparece en el soporte y en los logs |
| Límites | 429 con `Retry-After`; encabezados `RateLimit-Limit`, `RateLimit-Remaining` y `RateLimit-Reset` |

## 5. Catálogo inicial de endpoints

| Método y ruta | Scope | Servicio | Notas |
|---|---|---|---|
| `POST /api/oauth/token` | — | core | *Client credentials* |
| `GET /.well-known/jwks.json` | — | core | Claves públicas |
| `GET /api/v1/branches` | cualquiera | core | Sucursales permitidas para el cliente |
| `GET /api/v1/products` | `products:read` | core | Filtros `sku`, `barcode`, `search`, `updatedSince` |
| `GET /api/v1/products/{id}` | `products:read` | core | Incluye presentaciones |
| `POST /api/v1/products` | `products:write` | core | Idempotente |
| `PUT /api/v1/products/{id}` | `products:write` | core | Reemplazo de campos editables |
| `GET /api/v1/price-lists`, `GET /api/v1/price-lists/{id}/items` | `prices:read` | core | Etapa 5 |
| `GET /api/v1/stock` | `stock:read` | core | `branchId` obligatorio si el cliente tiene varias sucursales; `productId`, `updatedSince` |
| `GET /api/v1/customers` | `customers:read` | core | Filtro `identification` |
| `POST /api/v1/customers` | `customers:write` | core | Si existe la identificación, devuelve 409 con el id existente |
| `PUT /api/v1/customers/{id}` | `customers:write` | core | |
| `POST /api/v1/sales` | `sales:write` | core | Crea y confirma una venta de canal `api` en la sucursal y punto de emisión indicados; valida stock; idempotente |
| `GET /api/v1/sales`, `GET /api/v1/sales/{id}` | `sales:read` | core | Incluye estado de facturación |
| `POST /api/v1/sales/{id}/payments` | `sales:write` | core | Idempotente |
| `POST /api/v1/sales/{id}/cancel` | `sales:write` | core | Según reglas: antes de facturar o con nota de crédito |
| `GET /api/v1/invoices` | `invoices:read` | invoicing | Filtros `saleId`, `status`, `from`, `to`, `branchId` |
| `GET /api/v1/invoices/{id}` | `invoices:read` | invoicing | Número, clave de acceso, autorización |
| `GET /api/v1/invoices/{id}/xml`, `/ride` | `invoices:read` | invoicing | XML autorizado y PDF. Ya existen en la API interna (S4.1 y S4.4): `GET /api/invoices/{id}/authorized-xml` y `GET /api/invoices/{id}/ride`, adjuntos con la clave de acceso como nombre, 404 hasta que la factura esté autorizada; v1 los expone con otro prefijo y el scope |
| `GET/POST/DELETE /api/v1/webhook-endpoints` | `webhooks:manage` | core | |
| `POST /api/v1/webhook-endpoints/{id}/test` | `webhooks:manage` | core | Envía un evento de prueba |
| `GET /api/v1/webhook-endpoints/{id}/deliveries` | `webhooks:manage` | core | Últimos 30 días; reenvío con `POST .../{deliveryId}/retry` |

Caddy enruta `/api/v1/invoices*` a invoicing y el resto a core, bajo un solo dominio y un solo token.

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
    externalReference: "WEB-100234",
    customer: { identificationType: "NATIONAL_ID", identification: "1712345678" },
    items: [{ productId: 501, quantity: "3", unitPrice: "4.25" }],
    payments: [{ method: "TRANSFER", amount: "14.28" }],
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

### 7.1 Eventos iniciales

| Tipo | Cuándo | Datos principales |
|---|---|---|
| `sale.confirmed` | Venta confirmada (cualquier canal) | id, número, sucursal, totales, ítems, canal, `externalReference` |
| `sale.cancelled` | Venta anulada | id, motivo |
| `invoice.authorized` | Comprobante autorizado | id, venta, número, clave de acceso, fecha de autorización |
| `invoice.rejected` | Comprobante rechazado | id, venta, códigos del SRI |
| `credit_note.authorized` | Nota de crédito autorizada | id, factura de referencia |
| `stock.changed` | Cambió el disponible de un producto en una sucursal (agrupado cada 30 s) | producto, sucursal, disponible |
| `product.updated` | Alta o cambio de producto o precio | id, sku, campos cambiados |

### 7.2 Entrega

```http
POST /webhooks/faclab HTTP/1.1
Content-Type: application/json
webhook-id: msg_2Xf9…
webhook-timestamp: 1760461445
webhook-signature: v1,K5oZfzN95Z9UVu1EsfQmfVNQhnkZ2pj9o9NDN/H/pI4=

{"id":"msg_2Xf9…","type":"invoice.authorized","version":1,
 "occurredAt":"2026-10-14T15:04:05Z","tenantId":"8d1c…","data":{…}}
```

- La firma es HMAC-SHA256 con el secreto del endpoint, en base64, sobre
  `"{webhook-id}.{webhook-timestamp}.{cuerpo}"`. Se rechazan los mensajes con más de 5 minutos de
  antigüedad.
- Hay que responder 2xx en menos de 10 s; el procesamiento pesado se hace después.
- Reintentos con backoff exponencial durante hasta 3 días (por ejemplo, 5 s, 5 min, 30 min, 2 h, 5 h,
  10 h, 24 h, 24 h). Tras fallos sostenidos el endpoint se desactiva y se avisa a la empresa.
- El receptor deduplica por `webhook-id`. Los eventos pueden llegar desordenados: se usa `occurredAt` y
  el estado actual consultado por API cuando el orden importa.
- **Prevención de ciclos:** las escrituras hechas por un cliente de integración guardan su `azp` como
  origen, y el endpoint puede activar `excludeOwnChanges`. Además, `externalReference` permite que el
  sistema externo reconozca sus propios registros.

Verificación (Python):

```python
import base64, hmac, hashlib, time

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
- Por cliente y por empresa en la aplicación: por ejemplo, 600 solicitudes por minuto por cliente y
  ráfagas de 50. Son valores iniciales que se ajustan por plan.
- Almacén de contadores: decisión D-6. Redis cuando exista la API pública; PostgreSQL es aceptable si el
  volumen es bajo.
- Tamaño máximo de cuerpo de 1 MB y timeouts de lectura en Caddy.
- Endpoints de exportación masiva fuera del alcance inicial; se usa paginación con `updatedSince`.

## 10. Experiencia de integración

- **Documentación:** referencia generada del OpenAPI público (Scalar, ya usado en el core) más guías:
  autenticación, sincronizar catálogo y stock, crear ventas desde un ecommerce, recibir facturas por
  webhook.
- **Ejemplos** en `curl`, Python y JavaScript, ejecutados en CI contra el sandbox para que no se
  desactualicen.
- **Sandbox:** empresa de prueba por cliente con datos ficticios y facturación en el ambiente de
  pruebas del SRI. Las credenciales tienen el prefijo `fl_test_` y apuntan a
  `https://sandbox.<dominio>`.
- **SDK oficial:** solo cuando haya demanda de varios integradores. Mientras tanto, OpenAPI permite
  generar clientes.
- **Portal en la aplicación** (S6.5): clientes de integración (crear, rotar, revocar), scopes,
  sucursales, uso reciente, webhooks con historial de entregas y reenvío.
