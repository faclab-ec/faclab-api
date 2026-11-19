# Primeros pasos

Esta guía lleva de cero a una integración que funciona: credenciales, catálogo, una venta y sus
avisos por webhook. Todo se hace en el **sandbox**, una copia de Faclab con datos ficticios donde
las facturas van al ambiente de pruebas del SRI y no tienen valor tributario.

## 1. Pide tu sandbox

Escribe a soporte de Faclab. Te entregan:

- una **empresa de prueba** con datos ficticios: tres sucursales (Quito, Guayaquil y Cuenca), cada
  una con su punto de emisión y su bodega, unos 35 productos con stock, listas de precios, clientes
  y algunas ventas;
- un **usuario administrador** de esa empresa en la aplicación del sandbox;
- la dirección de la **API del sandbox**, `https://sandbox.<dominio>`. En los ejemplos se llama
  `FACLAB_API_URL`.

Lo que hagas en el sandbox no toca ninguna empresa real. Si quieres empezar de nuevo, pide que lo
restablezcan.

## 2. Crea un cliente de integración

En la aplicación, con tu usuario administrador: **Configuración → Integraciones → Nuevo cliente**.

1. Ponle un nombre que diga qué sistema es (por ejemplo, "Tienda en línea").
2. Marca los permisos (*scopes*) que tu sistema necesita. Para esta guía: `products:read`,
   `prices:read`, `stock:read`, `sales:read`, `sales:write`, `invoices:read` y `webhooks:manage`.
3. Deja **Todas las sucursales** y las **Redes de origen** vacías. Las puedes limitar después.
4. Guarda. Faclab muestra el **Client ID** (`fl_test_…`) y el **Secreto** una sola vez. Cópialos y
   guárdalos en el servidor de tu sistema, nunca en el código de una aplicación de navegador o
   móvil.

```bash
export FACLAB_API_URL=https://sandbox.<dominio>
export FACLAB_CLIENT_ID=fl_test_…
export FACLAB_CLIENT_SECRET=…
```

Si pierdes el secreto, en el detalle del cliente, pestaña **Secretos**, crea otro. Los detalles están
en [Autenticación](autenticacion.md).

## 3. Pide un token

```bash
curl -s "$FACLAB_API_URL/api/oauth/token" \
  -u "$FACLAB_CLIENT_ID:$FACLAB_CLIENT_SECRET" -d grant_type=client_credentials
```

```json
{"access_token": "eyJ…", "token_type": "Bearer", "expires_in": 900, "scope": "invoices:read prices:read …"}
```

Cada solicitud lleva `Authorization: Bearer <access_token>`. El token dura 15 minutos: cuando venza,
pide otro de la misma forma.

```bash
export TOKEN=$(curl -s "$FACLAB_API_URL/api/oauth/token" \
  -u "$FACLAB_CLIENT_ID:$FACLAB_CLIENT_SECRET" -d grant_type=client_credentials | jq -r .access_token)
```

## 4. Mira dónde puedes vender

```bash
curl -s "$FACLAB_API_URL/api/v1/branches" -H "Authorization: Bearer $TOKEN"
```

Cada sucursal trae sus **puntos de emisión**, que numeran las facturas, y sus **ubicaciones**, de
donde sale el stock. Anota el `id` de una sucursal, de su punto de emisión y de una ubicación.

## 5. Lee el catálogo y el stock

```bash
curl -s "$FACLAB_API_URL/api/v1/products?limit=5" -H "Authorization: Bearer $TOKEN"
curl -s "$FACLAB_API_URL/api/v1/stock?branchId=<sucursal>" -H "Authorization: Bearer $TOKEN"
```

Los montos y cantidades llegan como texto decimal (`"0.85"`). Cada producto trae su precio sin IVA
(`salePrice`) y su código de IVA (`taxCode`). Para mantener tu catálogo al día sin traer todo cada
vez, sigue [Sincronizar catálogo y stock](sincronizar-catalogo-y-stock.md).

## 6. Registra una venta

Un pedido pagado en tu tienda se registra así. El monto del pago es el total con IVA: un producto de
`0.85` con `VAT_15` suma `0.85 + 0.13 = 0.98`.

```bash
curl -s "$FACLAB_API_URL/api/v1/sales" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Branch-Id: <sucursal>" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"emissionPointId": <punto de emisión>, "locationId": <ubicación>,
       "externalReference": "WEB-0001",
       "items": [{"productId": <producto>, "quantity": "1"}],
       "payments": [{"method": "TRANSFER", "amount": "0.98", "reference": "pago-0001"}]}'
```

La respuesta (201) trae la venta con su número (`V-001-000123`) y su factura en camino
(`invoiceStatus: PENDING`). Repetir la solicitud con la misma `Idempotency-Key` no crea otra venta:
devuelve la misma. Todo lo que hay que saber de las ventas está en
[Ventas desde un ecommerce](ventas-desde-ecommerce.md).

## 7. Recibe los avisos por webhook

En lugar de consultar si la factura ya se autorizó, Faclab te avisa con un `POST` firmado a una URL
tuya.

1. Tu receptor tiene que estar en una dirección **HTTPS pública**. Mientras desarrollas, un túnel
   HTTPS hacia tu equipo sirve.
2. En la aplicación: **Configuración → Webhooks → Nuevo webhook**. Pon la URL, elige tu cliente
   como dueño y marca `sale.confirmed`, `invoice.authorized` e `invoice.rejected`. También se puede
   hacer por la API, como explica [Webhooks](webhooks.md).
3. En el detalle del webhook, **Mostrar secreto**: es lo que tu receptor usa para comprobar la
   firma.
4. Arranca el receptor de ejemplo con ese secreto, en
   [Python](examples/python/receptor_webhooks.py) o en [JavaScript](examples/javascript/receptor-webhooks.mjs):

   ```bash
   FACLAB_WEBHOOK_SECRET=whsec_… FACLAB_WEBHOOK_BIND=0.0.0.0 python receptor_webhooks.py
   ```

5. Pulsa **Probar** en el detalle del webhook. El receptor imprime `verificado webhook.test …` y el
   historial de entregas la muestra como entregada.
6. Registra otra venta (paso 6): llega `sale.confirmed`. Cuando el SRI la autorice, llega
   `invoice.authorized`, y con él se descarga la factura. Ver
   [Facturas por webhook](facturas-por-webhook.md).

## 8. Los ejemplos completos

Cada guía tiene su ejemplo en `curl`, Python y JavaScript. Todos leen `FACLAB_API_URL`,
`FACLAB_CLIENT_ID` y `FACLAB_CLIENT_SECRET`, y comprueban lo que hacen:

| Qué | curl | Python | JavaScript (Node 20+) |
|---|---|---|---|
| Token | [token.sh](examples/curl/token.sh) | [faclab.py](examples/python/faclab.py) | [faclab.mjs](examples/javascript/faclab.mjs) |
| Catálogo y stock | [catalogo-y-stock.sh](examples/curl/catalogo-y-stock.sh) | [sincronizar_catalogo.py](examples/python/sincronizar_catalogo.py) | [sincronizar-catalogo.mjs](examples/javascript/sincronizar-catalogo.mjs) |
| Venta, reintento y anulación | [venta.sh](examples/curl/venta.sh) | [crear_venta.py](examples/python/crear_venta.py) | [crear-venta.mjs](examples/javascript/crear-venta.mjs) |
| Registrar un webhook | [webhook.sh](examples/curl/webhook.sh) | | |
| Recibir webhooks y facturas | | [receptor_webhooks.py](examples/python/receptor_webhooks.py) | [receptor-webhooks.mjs](examples/javascript/receptor-webhooks.mjs) |

El cliente de Python solo necesita `httpx` (`pip install httpx`). El de JavaScript no tiene
dependencias. Los scripts de `curl` usan además `jq` y `bc`. Faclab corre todos estos ejemplos en
cada cambio contra un sandbox, así que siguen funcionando con la versión actual de la API.

## 9. Pasar a producción

Cuando tu integración funcione en el sandbox:

1. Pide a la empresa cliente que cree el cliente de integración en **su** Faclab de producción, con
   los mismos permisos. Ese cliente es `fl_live_…`.
2. Cambia `FACLAB_API_URL`, `FACLAB_CLIENT_ID` y `FACLAB_CLIENT_SECRET`. El código no cambia.
3. Registra allí tus webhooks y guarda su secreto.

Unas credenciales `fl_test_` no sirven en producción, ni unas `fl_live_` en el sandbox (401
`invalid_client`).
