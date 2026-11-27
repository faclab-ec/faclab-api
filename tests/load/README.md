# Pruebas de carga (S9.2)

Miden la capacidad del POS, de la API pública y de la facturación contra el stack de producción, en
una **copia desechable de staging**. Los resultados y la línea base están en
[docs/architecture/CARGA.md](../../docs/architecture/CARGA.md).

> **Nunca contra producción ni contra `celcer`.** Escriben miles de documentos. Los scripts se niegan
> con un host que no sea local o `*.test`, y el entorno de carga apunta la facturación al simulador
> del SRI.

## Qué hay

| Archivo | Para qué |
|---|---|
| `setup_data.py` | Llena por la API una empresa recién aprovisionada: 2 sucursales, 6 cajas con turno abierto, 10.000 productos, 2.000 presentaciones, 500 clientes, emisor y cliente de integración |
| `pos.js` | La venta en caja: buscar, escanear, precios, venta rápida y recibo (`RATE` ventas/min, `DURATION`, `MODE=contention`) |
| `public_api.js` | Sincronización de catálogo y stock y ventas por `/api/v1` (`READ_RATE`/s, `SALES_RATE`/min) |
| `reports.js` | Listados y reportes del administrador (`RATE`/min, `ONLY=<nombre>`) |
| `mixed.sh` | Hora pico: POS, API, reportes y un cambio de precios por importación, a la vez |
| `run.sh` | Corre un escenario con k6 (imagen `grafana/k6:1.3.0`) mientras muestrea el servidor (`LOAD_NO_SAMPLE=1` para no muestrear) |
| `server/sample.sh` | En el servidor: conexiones, esperas, outbox, comprobantes, CPU, memoria y lag de Kafka |
| `server/after.sql` | Tiempos de outbox y de autorización de la corrida, medidos por las bases |
| `server/history.sql` | Multiplica las ventas generadas en meses de historia, para medir listados y reportes |
| `summarize.py` | Máximos y promedios de lo muestreado |

k6 es la única herramienta nueva y se usa como imagen: no entra en `requirements*.txt`.

## Perfil de la ferretería piloto

| | Valor |
|---|---|
| Sucursales y cajas | 2 y 6 (3 por sucursal) |
| Ventas al día | ~600; pico de la mañana (07:30 a 10:00) de 4 ventas por minuto |
| Catálogo | 10.000 productos, 1 de cada 5 con caja x25; stock en las dos bodegas |
| Clientes | 500; un cuarto con crédito, un cuarto con lista de precios |
| Cada venta | 1 a 8 líneas (3 en promedio); 70 % consumidor final (bajo USD 50), 20 % cliente con lista, 10 % a crédito |

## Preparar el entorno

En la Mac, con la VM de staging de [OrbStack](https://orbstack.dev) detenida (solo una puede
publicar los puertos 80 y 443) y la Mac **enchufada**.

```bash
orbctl clone faclab-staging faclab-load
orbctl config set machine.faclab-load.cpu 4 && orbctl restart faclab-load   # como el VPS de 4 vCPU

# Imágenes de lo que se va a medir, sin publicarlas
docker build --target production --build-arg SERVICE_VERSION=load -t faclab-load/core:master ../faclab-core
docker build --target production --build-arg SERVICE_VERSION=load -t faclab-load/invoicing:master ../faclab-invoicing
docker save faclab-load/core:master faclab-load/invoicing:master node:22-bookworm-slim |
  orb -m faclab-load -u root docker load
```

En la copia (`orb -m faclab-load -u root bash`):

1. Deja el checkout de faclab-infra (`/opt/faclab/faclab-infra`) en la versión que se prueba.
2. En `/etc/faclab/deployments/current.env`, apunta `CORE_IMAGE` e `INVOICING_IMAGE` a
   `faclab-load/core:master` y `faclab-load/invoicing:master`.
3. Migra y levanta con el override de carga:

   ```bash
   cd /opt/faclab/faclab-infra/deploy/production
   ./scripts/stack.sh migrate
   ./scripts/stack.sh compose -f load/compose.load.yaml up -d --wait
   ```

4. Aprovisiona la empresa de prueba (`PROVISION_ADMIN_PASSWORD` en el entorno):

   ```bash
   ./scripts/stack.sh compose run --rm --no-deps -e PROVISION_ADMIN_PASSWORD core-api \
     python -m src.tenancy.provision --ruc 1799999990001 --legal-name "Ferreteria de carga" \
     --admin-username load-admin --admin-email load-admin@example.com
   ```

5. Copia `server/sample.sh`, `server/after.sql` y `server/history.sql` a `/opt/load/`.

Variables del override, delante de `stack.sh compose` (se aplican al recrear el contenedor):

| Variable | Por defecto | Efecto |
|---|---|---|
| `CORE_WEB_CONCURRENCY` | 2 | Procesos de uvicorn del core |
| `LOAD_PUBLIC_RATE_LIMIT` | `true` | `false` quita los límites de la API pública para medir capacidad |
| `LOAD_SRI_DELAY_MS` | 800 | Lo que tarda cada operación del simulador del SRI |
| `LOAD_SRI_PENDING` | vacío | `01`: la factura queda `EN PROCESO` la primera vez |
| `LOAD_TELEMETRY_EXPORTER` | `nop` | `otlp_grpc/signoz` para verla en el SigNoz local |

## Datos y corridas

La raíz de la CA de Caddy sale de
`docker exec faclab-caddy-1 cat /data/caddy/pki/authorities/local/root.crt`, y `api.faclab.test` va
en `/etc/hosts` hacia `127.0.0.1`. Las contraseñas, el archivo de datos y los resultados quedan
**fuera del repositorio**.

```bash
LOAD_BASE_URL=https://api.faclab.test LOAD_CA_FILE=$DIR/caddy-root.crt LOAD_RUC=1799999990001 \
LOAD_ADMIN_USERNAME=load-admin LOAD_ADMIN_PASSWORD=... \
  .venv/bin/python tests/load/setup_data.py --fixtures $DIR/fixtures.json

export LOAD_FIXTURES=$DIR/fixtures.json LOAD_RESULTS=$DIR/results
caffeinate -ims tests/load/run.sh peak pos.js RATE=4 DURATION=15m
caffeinate -ims tests/load/run.sh stress-300 pos.js RATE=300 DURATION=2m
caffeinate -ims tests/load/run.sh contention pos.js RATE=300 DURATION=2m MODE=contention
caffeinate -ims tests/load/run.sh api public_api.js READ_RATE=5 SALES_RATE=4 DURATION=5m
caffeinate -ims tests/load/run.sh reports reports.js RATE=12 DURATION=5m

# La hora mixta importa precios: necesita además LOAD_BASE_URL, LOAD_CA_FILE y las credenciales
caffeinate -ims tests/load/mixed.sh 5m
```

En la hora mixta, las ventas por API posteriores a la importación se rechazan con
`INSUFFICIENT_PAYMENT`: la tienda simulada paga con el precio anterior. Es lo esperado.

La facturación acumula cola por encima de unas 110 ventas por minuto y no estorba para medir el POS.
Su ritmo se mide contando las facturas autorizadas por minuto mientras la cola se vacía. Para ver las
alertas contra SigNoz, antes de levantarlo apunta el canal de Telegram a un bot inválido (o quita sus
variables en una instalación nueva): las reglas avisan de verdad.

Los turnos quedan abiertos entre corridas. Al terminar:

```bash
orbctl delete faclab-load
```
