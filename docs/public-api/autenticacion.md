# Autenticación

## Cliente de integración

Un administrador de la empresa crea el cliente en Faclab (`POST /api/admin/integrations`; el portal
llega con S6.5) y elige:

- los **scopes**: qué recursos puede leer o escribir;
- las **sucursales** (opcional): sin ninguna, todas;
- las **redes** de origen en CIDR (opcional): sin ninguna, cualquiera.

Recibe un `client_id` (`fl_live_…` en producción, `fl_test_…` en el sandbox) y un secreto que se
muestra **una sola vez**. Guárdalo en el servidor del integrador, nunca en una aplicación móvil o de
navegador. Puede tener dos secretos activos para rotarlos sin cortar el servicio.

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

El endpoint sigue OAuth 2.0 (RFC 6749): sus errores son `{"error", "error_description"}`, por ejemplo
401 `invalid_client`. Cualquier biblioteca OAuth sirve. El token dura 15 minutos y no hay refresh:
pide otro cuando venza.

Cada solicitud lleva `Authorization: Bearer <token>`. La empresa sale del token: ningún endpoint
recibe un id de empresa.

## Scopes

| Scope | Permite |
|---|---|
| `products:read` / `products:write` | Leer productos y presentaciones / crearlos y actualizarlos |
| `prices:read` | Listas de precios |
| `stock:read` | Stock por sucursal |
| `customers:read` / `customers:write` | Clientes |
| `sales:read` / `sales:write` | Leer ventas / crearlas y anular las propias |
| `invoices:read` | Facturas y notas de crédito, su XML y RIDE |

`GET /api/v1/branches` acepta cualquier scope. Sin el scope de una ruta: 403 `INSUFFICIENT_SCOPE`.

## Sucursales

Un cliente limitado a algunas sucursales solo ve sus ventas, stock y comprobantes. Una operación
de sucursal (crear una venta) la indica con `X-Branch-Id`; una sucursal que el cliente no puede usar
responde 403 `BRANCH_ACCESS_DENIED`.

## Revocación

Revocar el cliente o un secreto invalida sus tokens en el core en menos de un minuto (401
`INVALID_TOKEN`). Facturación no consulta el estado del cliente: allí un token ya emitido vale hasta
que vence, como máximo 15 minutos.
