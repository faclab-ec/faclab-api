# Autenticación

## Cliente de integración

Cada sistema que se conecta a Faclab (una tienda en línea, un ERP) es un **cliente de integración**
de una empresa. Lo crea un administrador de la empresa en la aplicación: **Configuración →
Integraciones → Nuevo cliente**. Ahí elige:

- los **scopes**: qué recursos puede leer o escribir (tabla abajo);
- las **sucursales**: todas, también las que se creen después, o algunas;
- las **redes de origen** en CIDR (`203.0.113.7`, `198.51.100.0/24`), hasta 20. Sin ninguna, se
  acepta cualquier origen.

Al guardar, Faclab muestra un `client_id` y un secreto **una sola vez**: solo guarda un hash del
secreto, así que nadie lo puede volver a ver. El `client_id` empieza por `fl_test_` en el sandbox y
por `fl_live_` en producción, y cada uno solo sirve en su ambiente. Guarda el secreto en el servidor
de tu sistema, nunca en una aplicación de navegador o móvil.

El detalle del cliente en la aplicación muestra además sus secretos, su **uso por día** de los
últimos 30 días (tokens emitidos y rechazados, solicitudes y errores) y sus webhooks.

## Token

```bash
curl -s https://api.<dominio>/api/oauth/token \
  -u "$FACLAB_CLIENT_ID:$FACLAB_CLIENT_SECRET" \
  -d grant_type=client_credentials \
  -d scope="products:read stock:read sales:write"   # opcional: un subconjunto
```

```json
{"access_token": "eyJ…", "token_type": "Bearer", "expires_in": 900, "scope": "products:read sales:write stock:read"}
```

El endpoint sigue OAuth 2.0 *client credentials* (RFC 6749). El id y el secreto van con HTTP Basic,
como arriba, o en el formulario (`client_id` y `client_secret`). Sus errores son
`{"error", "error_description"}`, por ejemplo 401 `invalid_client` con credenciales que no existen,
de otro ambiente o revocadas. Cualquier biblioteca OAuth sirve.

El token dura 15 minutos y no hay refresh: guárdalo y pide otro cuando venza, o un minuto antes.
Cada solicitud lleva `Authorization: Bearer <token>`. La empresa sale del token: ningún endpoint
recibe un id de empresa.

Los ejemplos [faclab.py](examples/python/faclab.py) y [faclab.mjs](examples/javascript/faclab.mjs)
piden el token, lo reutilizan mientras vale y piden otro al vencer.

## Scopes

| Scope | Permite |
|---|---|
| `products:read` | Leer productos, categorías, unidades y presentaciones |
| `products:write` | Crear y actualizar productos |
| `prices:read` | Leer las listas de precios |
| `prices:write` | Cambiar las listas de precios |
| `stock:read` | Leer el stock por sucursal, bodega y ubicación |
| `inventory:write` | Documentos de inventario (ajustes, transferencias) |
| `customers:read` / `customers:write` | Leer clientes / crearlos y actualizarlos |
| `sales:read` | Leer ventas |
| `sales:write` | Crear ventas y anular las propias |
| `invoices:read` | Facturas y notas de crédito, su XML y su RIDE |
| `webhooks:manage` | Registrar y administrar sus propios webhooks |

`GET /api/v1/branches` acepta cualquier scope. Sin el scope de una ruta, la respuesta es 403
`INSUFFICIENT_SCOPE`. Un webhook solo recibe los eventos de lo que su cliente puede leer: para
`invoice.authorized` hace falta `invoices:read`.

## Sucursales

Un cliente limitado a algunas sucursales solo ve sus ventas, su stock y sus comprobantes, y solo
recibe sus eventos. Una operación de sucursal (crear una venta) la indica con `X-Branch-Id`. Una
sucursal que el cliente no puede usar responde 403 `BRANCH_ACCESS_DENIED`.

## Rotar el secreto

Un cliente puede tener **dos secretos activos**, así se cambia sin cortar el servicio. En la pestaña
**Secretos** del cliente:

1. **Nuevo secreto**. Faclab muestra el nuevo una sola vez y pregunta cuánto siguen valiendo los
   activos: 1, 7 o 30 días, dejar de valer ahora o seguir hasta revocarlos.
2. Cambia el secreto en tu sistema dentro de ese plazo.
3. Si no esperaste a que venza, revoca el anterior.

Con dos secretos activos, uno tiene que vencer antes de crear otro
(`INTEGRATION_SECRET_LIMIT_REACHED`).

## Revocación

Revocar un secreto o el cliente entero invalida sus tokens en menos de un minuto (401
`INVALID_TOKEN`). Revocar el cliente es definitivo y desactiva sus webhooks: para volver a conectar
ese sistema, se crea otro cliente. Las facturas (`/api/v1/invoices`) no consultan el estado del
cliente: allí un token ya emitido vale hasta que vence, como máximo 15 minutos.
