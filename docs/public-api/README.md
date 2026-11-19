# API pública de Faclab (`/api/v1`)

La API para integraciones: un contrato propio, versionado en la URL, que no cambia con la aplicación
web. Esta carpeta es su documentación. La API la publica en **`/docs/public`**: estas guías, la
referencia de todas las rutas y los eventos de webhook en una sola página. También publica los
ejemplos y los esquemas de esta carpeta en `/docs/public/files/`.

| Guía | Contenido |
|---|---|
| [Primeros pasos](primeros-pasos.md) | Del sandbox a una venta con su aviso por webhook, de punta a punta |
| [Autenticación](autenticacion.md) | Cliente de integración, token, scopes, sucursales y rotación del secreto |
| [Sincronizar catálogo y stock](sincronizar-catalogo-y-stock.md) | `updatedSince`, orden estable, paginación |
| [Ventas desde un ecommerce](ventas-desde-ecommerce.md) | Una venta pagada en línea, su total, reintentos, anulación y su factura |
| [Facturas por webhook](facturas-por-webhook.md) | `invoice.authorized`, el XML y el RIDE, rechazos y notas de crédito |
| [Webhooks](webhooks.md) | Registrar endpoints, los eventos, verificar la firma, reintentos y reenvío |
| [Errores](errores.md) | El catálogo de códigos y qué hacer con cada uno |
| [Límites de solicitudes](limites.md) | Encabezados `RateLimit-*`, 429 y `Retry-After` |
| [Cambios](CHANGELOG.md) | Qué cambió en cada versión del contrato |

Los [ejemplos](examples/README.md) en `curl`, Python y JavaScript cubren cada guía y se ejecutan en
cada cambio contra un sandbox.

## Ambientes

| Ambiente | API | Credenciales |
|---|---|---|
| Sandbox | `https://sandbox.<dominio>` | `fl_test_…`: empresa de prueba con datos ficticios, facturas en el ambiente de pruebas del SRI |
| Producción | `https://api.<dominio>` | `fl_live_…`: las crea el administrador de cada empresa |

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

## Para quien mantiene este repositorio

Diseño y decisiones: [PUBLIC_API.md](../architecture/PUBLIC_API.md),
[ADR-0008](../architecture/ADR/0008-api-publica-versionada-y-credenciales-de-integracion.md) y
[ADR-0009](../architecture/ADR/0009-webhooks-firmados.md). Las guías de arriba son para integradores
sin acceso al código: no enlazan a esos documentos. En la página pública, los enlaces entre guías se
vuelven texto en negrita (están en la misma página) y los enlaces a archivos de esta carpeta
apuntan a `/docs/public/files/`.

- [`openapi-v1.json`](openapi-v1.json): el contrato de las rutas del core y del endpoint de token.
  `make public-openapi` lo regenera desde el código, junto con [`webhooks/v1/`](webhooks/v1/), el
  JSON Schema de cada evento, y una prueba falla mientras difieran. El CI compara la versión de cada
  PR con la de `master` (`oasdiff`): quitar o renombrar un campo, cambiar un tipo o volver
  obligatorio un campo de entrada hace fallar el job `public-api-compat`. Un cambio así necesita
  `/api/v2` y al menos seis meses de convivencia (PUBLIC_API.md §8).
- [`invoicing/openapi-v1.json`](invoicing/openapi-v1.json): copia fijada del contrato de
  `/api/v1/invoices`, que sirve faclab-invoicing bajo el mismo dominio y con el mismo token. La
  página pública la une a la del core (`src/public_api/infra/docs.py`). `make public-openapi-invoicing`
  la copia de `../faclab-invoicing` (o de `d=<ruta>`) después de un cambio allí.
- Los [ejemplos](examples/) los corre el job `examples` del CI contra un core de sandbox levantado
  en el mismo job (`examples/run-all.sh`). Un cambio que rompa una guía rompe el job.
- La empresa de sandbox de cada integrador se crea con `make sandbox`: ver
  [docs/sandbox.md](../sandbox.md).
- `PUBLIC_DOCS_ENABLED=false` oculta `/docs/public`; el contrato sigue en `/openapi/public.json`.
