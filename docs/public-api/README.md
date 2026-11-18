# API pública de Faclab (`/api/v1`)

La API para integraciones: un contrato propio, versionado en la URL, que no cambia con la aplicación
web. Diseño y decisiones en [PUBLIC_API.md](../architecture/PUBLIC_API.md) y
[ADR-0008](../architecture/ADR/0008-api-publica-versionada-y-credenciales-de-integracion.md).

| Guía | Contenido |
|---|---|
| [Autenticación](autenticacion.md) | Cliente de integración, token, scopes y sucursales |
| [Sincronizar catálogo y stock](sincronizar-catalogo-y-stock.md) | `updatedSince`, orden estable, paginación |
| [Ventas desde un ecommerce](ventas-desde-ecommerce.md) | Crear una venta pagada en línea, reintentos, anulación y su factura |
| [Errores](errores.md) | El catálogo de códigos y qué hacer con cada uno |
| [Límites de solicitudes](limites.md) | Encabezados `RateLimit-*`, 429 y `Retry-After` |
| [Webhooks](webhooks.md) | Registrar endpoints, los eventos, verificar la firma, reintentos y reenvío |
| [Cambios](CHANGELOG.md) | Qué cambió en cada versión del contrato |

## El contrato

- [`openapi-v1.json`](openapi-v1.json): los recursos del core (sucursales, productos, listas de
  precios, stock, clientes y ventas) y el endpoint de token. La API lo sirve en
  `GET /openapi/public.json` y, en local, como referencia interactiva en `/docs/public`.
- [`webhooks/v1/`](webhooks/v1/): el JSON Schema de cada evento que se envía por webhook (S6.4).
- Los comprobantes (`/api/v1/invoices`, facturas y notas de crédito con su XML y RIDE) los sirve
  faclab-invoicing bajo el mismo dominio y con el mismo token: su contrato está en
  `faclab-invoicing/docs/public-api/openapi-v1.json`.

`make public-openapi` regenera el archivo y los esquemas de los webhooks desde el código, y una
prueba falla mientras difieran. El CI
compara la versión de cada PR con la de `master` (`oasdiff`): quitar o renombrar un campo, cambiar
un tipo o volver obligatorio un campo de entrada hace fallar el job `public-api-compat`. Un cambio así
necesita `/api/v2` y al menos seis meses de convivencia (PUBLIC_API.md §8).

## En pocas líneas

```bash
# 1. Token (válido 15 minutos: guárdalo y pide otro al vencer)
curl -s https://api.<dominio>/api/oauth/token \
  -u "$FACLAB_CLIENT_ID:$FACLAB_CLIENT_SECRET" -d grant_type=client_credentials

# 2. Dónde puede vender el cliente
curl -s https://api.<dominio>/api/v1/branches -H "Authorization: Bearer $TOKEN"

# 3. Stock de una sucursal
curl -s "https://api.<dominio>/api/v1/stock?branchId=12" -H "Authorization: Bearer $TOKEN"
```

Convenciones: JSON en camelCase; dinero y cantidades como texto decimal (`"12.50"`, `"2.5"`), nunca
números con decimales; fechas ISO 8601 en UTC; `{data, meta}` en las respuestas y
`{errors: [{code, message, field?}], meta}` en los errores; `meta.requestId` (y el encabezado
`X-Request-Id`) identifica la solicitud ante soporte. Ignora los campos que no conozcas: se agregan
sin cambiar de versión.
