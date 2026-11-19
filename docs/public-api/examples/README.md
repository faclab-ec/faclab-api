# Ejemplos de la API pública

Cada guía tiene su ejemplo en `curl`, Python y JavaScript. Todos leen la configuración del entorno y
comprueban lo que hacen: si la API cambiara de una forma que rompe una guía, el ejemplo falla.

```bash
export FACLAB_API_URL=https://sandbox.<dominio>   # por defecto http://localhost:3000
export FACLAB_CLIENT_ID=fl_test_…
export FACLAB_CLIENT_SECRET=…
```

| Carpeta | Necesita | Archivos |
|---|---|---|
| `curl/` | bash, curl, jq, bc | `token.sh`, `catalogo-y-stock.sh`, `venta.sh`, `webhook.sh` |
| `python/` | Python 3.11+, `pip install -r requirements.txt` (solo httpx) | `faclab.py` (el cliente), `sincronizar_catalogo.py`, `crear_venta.py`, `receptor_webhooks.py` |
| `javascript/` | Node 20+, sin dependencias | `faclab.mjs` (el cliente), `sincronizar-catalogo.mjs`, `crear-venta.mjs`, `receptor-webhooks.mjs` |

```bash
cd python && python crear_venta.py
cd javascript && node crear-venta.mjs
cd curl && ./venta.sh
```

`crear_venta` registra una venta de un producto con stock de la primera sucursal, la reintenta con
la misma `Idempotency-Key` y la anula, así que el stock queda como estaba. Con la factura ya en
camino, Faclab no la deja anular y el ejemplo lo informa.

Los receptores de webhooks escuchan en `FACLAB_WEBHOOK_BIND:FACLAB_WEBHOOK_PORT` (por defecto
`127.0.0.1:8000`) con el secreto del endpoint en `FACLAB_WEBHOOK_SECRET`. Faclab solo envía a URLs
HTTPS públicas: mientras desarrollas, exponlos con un túnel HTTPS.

## Todos a la vez

`run-all.sh` corre todos los ejemplos en orden y, para los webhooks, levanta cada receptor, registra
su endpoint, pide una prueba, crea una venta y espera los dos eventos con la firma comprobada. Es lo
que corre el CI de Faclab en cada cambio, contra un core de sandbox levantado en el mismo job:

```bash
FACLAB_API_URL=http://localhost:3000 FACLAB_CLIENT_ID=… FACLAB_CLIENT_SECRET=… ./run-all.sh
```

Los receptores locales solo reciben de una API que pueda llegar a ellos y acepte URLs privadas (un
core local con `WEBHOOK_ALLOW_PRIVATE_URLS=true`). Contra el sandbox público,
`FACLAB_SKIP_WEBHOOKS=1` salta esa parte.
