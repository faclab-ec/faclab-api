# Pruebas de carga y línea base (S9.2)

Medido el 2026-11-26. Escenarios y forma de repetirlo: [tests/load/README.md](../../tests/load/README.md).

## 1. Resumen

- **El POS aguanta unas 600 ventas por minuto** en 4 vCPU con la venta rápida bajo 0,65 s (p95): unas
  150 veces el pico de la ferretería piloto (4 por minuto). La degradación empieza hacia las 750.
- **La facturación procesa unas 110 facturas por minuto** con el simulador del SRI a 800 ms por
  operación. Es el paso más lento del flujo: las ventas no esperan, la cola sí.
- **La API pública sostiene unas 50 lecturas por segundo** de 200 elementos (p95 65 ms), 2,5 veces el
  límite por empresa.
- **El VPS de 4 vCPU y 8 GB sobra para el piloto.** Lo primero que se agota es la CPU.
- **Dos defectos encontrados:** un interbloqueo de la API pública (corregido en esta sesión) y la
  exportación de datos, que falla en el stack de producción (pendiente).

> Son cifras de **referencia**, no de un VPS: ver [§2.3](#23-límites-de-la-medición).

## 2. Cómo se midió

### 2.1 Entorno

| | |
|---|---|
| Servidor | Copia desechable de la VM de staging (OrbStack), limitada a **4 vCPU**, 5,9 GB de RAM visibles |
| Anfitrión | Mac Apple Silicon de 8 núcleos y 8 GB; k6 corre en la misma Mac, fuera de la VM |
| Stack | El compose de producción de faclab-infra, con imágenes construidas desde `master` (core `b910426`, invoicing `ede30d0`) |
| Cambios para la prueba | SRI simulado (800 ms por operación, autoriza a la primera consulta), límites por IP del borde abiertos, telemetría en `nop` como hoy en producción, logs de facturación en `warn` (`deploy/production/load/compose.load.yaml`) |
| Configuración | La de producción: `CORE_WEB_CONCURRENCY=2`, `INVOICE_WORKER_CONCURRENCY=4`, `max_connections=150` |
| Herramienta | k6 1.3.0, llegada a tasa constante |

Nunca se envió carga a `celcer` ni a producción.

### 2.2 Perfil

Ferretería mediana: 2 sucursales, 6 cajas, unas 600 ventas al día con un pico de 4 por minuto, 10.000
productos (2.000 con caja x25), 500 clientes y stock en las dos bodegas. Cada venta busca un producto,
escanea hasta tres, resuelve precios, hace la venta rápida (1 a 8 líneas, 3 en promedio) y pide el
recibo; 70 % consumidor final, 20 % cliente con lista de precios y 10 % a crédito.

Los datos se cargaron por la API con la importación masiva: 10.000 productos en 58 s y 20.000 filas de
stock en 149 s.

### 2.3 Límites de la medición

- Los núcleos de la Mac son bastante más rápidos que un vCPU típico de VPS: las latencias reales
  serán mayores y la capacidad menor. **Hay que repetir la medición en el primer VPS.**
- El simulador no es el SRI: su latencia es fija y no devuelve `EN PROCESO` ni caídas.
- Una sola empresa con datos: el efecto de muchas empresas en índices y límites no se midió.
- Sin respaldos (`BACKUPS=off`) y sin el correo de entrega de facturas.
- Los escalones duran 1,5 a 2 minutos: dan capacidad, no estabilidad de horas.

## 3. Línea base en el pico del piloto

4 ventas por minuto durante 15 minutos (61 ventas, ningún error):

| Medida | Mediana | p95 |
|---|---|---|
| Venta rápida | 67 ms | 100 ms |
| Búsqueda de productos | 72 ms | 96 ms |
| Resolución de precios | 58 ms | 66 ms |
| Código de barras | 50 ms | 57 ms |
| Recibo | 27 ms | 56 ms |
| Outbox: de escrito a publicado | 0,54 s | 0,97 s |
| Factura: de pedida a autorizada | 2,7 s | 3,3 s |

CPU media del core: 4 % de un núcleo. Conexiones de PostgreSQL: 20 como máximo. Lag de Kafka: 0.

## 4. Capacidad del POS

### 4.1 Rampa (2 procesos del core)

| Ventas/min pedidas | Ventas/min logradas | Venta rápida p95 | Errores | Qué se vio |
|---|---|---|---|---|
| 60 | 60 | 97 ms | 0 | |
| 150 | 146 | 125 ms | 0 | |
| 300 | 294 | 155 ms | 0 | |
| 600 | 580 | 0,54 a 0,63 s | 0 | CPU del core alrededor de 1,6 a 2 núcleos |
| 750 | 730 | 2,0 s | 0 | Los 2 procesos saturados |
| 900 | 700 a 760 | 6 a 7 s | 0 | Hasta 24 sesiones esperando el contador de numeración |

**Capacidad** (p95 < 1,5 s y errores < 1 %): entre 600 y 750 ventas por minuto.

Hubo dos rampas. En la primera (60 a 900) faclab-invoicing todavía escribía sus logs en formato de
desarrollo, que gasta CPU; la segunda (600 a 900, con los logs en `warn`) dio cifras parecidas.

### 4.2 Cuello de botella

1. **CPU del core.** Cada proceso de uvicorn usa un núcleo (GIL) y los dos llegan al tope.
2. **El contador de numeración de la sucursal** (`document_sequences`). La fila queda bloqueada desde
   que se toma el número (paso 7 de `src/pos/sales/app/checkout.py`) hasta el commit, así que las
   ventas de una sucursal se serializan en ese tramo. Con la CPU saturada el tramo se alarga y las
   esperas llegan a 13 s.

Ambos van juntos: el bloqueo no limita mientras haya CPU libre.

### 4.3 Más procesos no ayudan

Con `CORE_WEB_CONCURRENCY=4` en los mismos 4 vCPU:

| Ventas/min pedidas | 2 procesos: logradas / p95 | 4 procesos: logradas / p95 |
|---|---|---|
| 600 | 579 / 0,6 s | 571 / 1,5 s |
| 750 | 730 / 2,0 s | 612 / 12,5 s |
| 900 | 763 / 6,0 s | 537 / 17,1 s |

Hay menos CPU para cada transacción, retienen más tiempo el contador (esperas de hasta 38 s) y las
conexiones llegan a 144 de 150. **Se queda en 2.**

### 4.4 Contención de stock

Las 3 cajas de una sucursal vendiendo siempre los mismos 5 productos:

| Ventas/min | Venta rápida p95 | Errores | Espera máxima por una fila de stock |
|---|---|---|---|
| 150 | 234 ms | 0 | — |
| 300 | 287 ms | 0 | — |
| 450 | 483 ms | 0 | 0,2 s |
| 600 | 651 ms | 0 | 0,7 s |

Sin interbloqueos ni errores: el bloqueo ordenado de las filas funciona.

### 4.5 Integridad después de la carga

Con 15.746 ventas concurrentes:

- numeración consecutiva en cada sucursal, sin huecos ni repetidos;
- las 20.001 filas de stock iguales a la suma de sus movimientos, ninguna negativa;
- los pagos aplicados de cada venta iguales a su total;
- ningún mensaje `failed` en el outbox ni en `dead_letters` del core.

## 5. Facturación

| `INVOICE_WORKER_CONCURRENCY` | Facturas autorizadas por minuto |
|---|---|
| 4 (por defecto) | 112 |
| 6 (el máximo con 2 entregas) | 146 |

- Cada comprobante ocupa 2,2 a 2,5 s de un hueco del worker, de los que 1,6 s son esperas al SRI
  simulado. Con el SRI real manda su latencia: capacidad ≈ concurrencia ÷ (2 × latencia + 0,6 s).
- El pico del piloto (4 por minuto) usa menos del 5 %. Las 600 ventas de un día completo, juntas,
  tardarían unos 6 minutos.
- El worker consume hasta 2 núcleos en ráfagas (firma, XSD y RIDE), que compiten con el core.
- El outbox no se atrasa: en las corridas de capacidad el mensaje más antiguo no pasó de 2,4 s, y el
  lag de Kafka no pasó de 6 mensajes.

## 6. API pública

| Escenario | Resultado |
|---|---|
| Límites por defecto, 20 lecturas/s | Se atienden unas 10/s (600 por minuto); las 859 respuestas 429 llevaron `Retry-After` |
| Sin límites, 25 lecturas/s | p95 57 ms |
| Sin límites, 50 lecturas/s | p95 65 ms |
| Sin límites, 100 lecturas/s | Saturada: 88/s, p95 1,9 s |
| Ventas `api`, 150 / 300 / 600 por minuto | p95 100 / 97 / 172 ms, sin errores |

Las páginas son de 200 elementos. El límite por empresa (1.200 por minuto, 20/s) queda muy por debajo
de la capacidad, pero cuatro empresas usándolo a la vez ya la ocuparían.

Cada solicitud de un cliente actualiza su fila de uso del día: todas las de un mismo cliente se
serializan en ella (29 sesiones esperando a 100/s).

## 7. Consultas del administrador

Con unos 6 meses de historia (110.000 ventas, 320.000 líneas, 340.000 movimientos; base de 330 MB):

| Consulta | p95 o tiempo |
|---|---|
| Listados de ventas, productos, clientes, stock, cartera y bitácora | 76 a 160 ms |
| Listado de movimientos | 280 ms |
| Reporte diario y por método de pago del POS | 200 a 320 ms |
| Valoración y kárdex | 80 a 380 ms |
| Rotación (1,8 MB sin paginar) | 380 ms |
| Dashboard | 770 ms (530 ms leyendo las 20.000 filas de stock) |

**Índices compuestos `(tenant_id, …)`** (pendiente del ROADMAP desde S2.4): a esta escala no hacen
falta; las consultas más lentas son agregados que leen todo. Queda por medir con muchas empresas en la
misma base.

## 8. Hora mixta

POS al doble del pico, una tienda en línea (5 lecturas/s y 4 ventas/min), 12 consultas del
administrador por minuto y un cambio de precio de los 10.000 productos por importación, a la vez:

- venta rápida p95 157 ms; lecturas de la API p95 110 ms; ningún error del servidor;
- la importación terminó en 77 s sin afectar las cajas;
- el reporte diario llegó a 1,3 s (tres muestras);
- 15 ventas por API se rechazaron con `INSUFFICIENT_PAYMENT`: la tienda simulada pagó con el precio
  anterior. Es lo esperado.

## 9. Hallazgos

### 9.1 Corregido: interbloqueo al pedir tokens

Emitir un token actualizaba el cliente y después la fila de uso del día; cada solicitud del cliente
(`record_request`) lo hace al revés. Pedir un token mientras se usaba otro provocaba interbloqueos
(S6.2): con 40 solicitudes y 40 tokens a la vez, esperas de hasta 30 s y **19 tokens con 500**. Una
búsqueda del POS hecha durante el atasco respondió en 70 ms.

Corregido en `src/integrations/app/commands/token.py` (mismo orden en ambos), con prueba en
`tests/integration/postgres/test_integrations.py`. Con el arreglo: las 80 en 1 s y ningún
interbloqueo.

### 9.2 Pendiente: la exportación de datos falla en producción

`POST /api/admin/data-exports` (S8.7) termina en `FAILED` con `OSError`: el compose de producción de
faclab-infra no define `DATA_EXPORT_DIR` ni un volumen compartido entre la API y el worker, y el
sistema de archivos es de solo lectura. Se corrige en faclab-infra antes del piloto.

### 9.3 Mejoras anotadas, sin implementar

Ninguna hace falta para el volumen del piloto.

| Mejora | Para qué |
|---|---|
| Tomar el número de la venta lo más cerca posible del commit | Acortar la serialización por sucursal |
| Perfilar la venta rápida para gastar menos CPU | Subir la capacidad por núcleo |
| Hacer configurable el pool de SQLAlchemy (hoy 5 + 10 por motor y proceso) | Con más procesos las conexiones se acercan a `max_connections` |
| Dimensionar el pool para no responder 500 al saturarse (§10.1) | Hoy esperan 30 s y fallan |
| Pasar `INVOICE_WORKER_CONCURRENCY` en el compose de producción | Poder subir la capacidad de facturación sin cambiar código |
| Contar el uso de integraciones por lotes o sin una sola fila por cliente | Quitar la serialización de la API pública por cliente |
| Agregar en SQL el stock del dashboard; paginar valoración y rotación | Crecen con el catálogo |

## 10. Umbrales de las alertas

| Alerta | Antes | Ahora | Razón |
|---|---|---|---|
| `latencia-pos` | p95 > 1,5 s | **> 1 s** | El p95 es 0,1 s en el pico y 0,65 s a 150 veces el pico |
| `outbox-atascado` | 5 min / 15 min | **2 min / 10 min** | Lo normal es menos de 2,4 s incluso saturado |
| `rechazos-sri` | `faclab.invoices.rejections` | **`faclab.invoices.transitions` hacia `rejected`** | Series acotadas; antes cada código nuevo perdía su primer punto |
| `facturas-atascadas` | 30 min | Igual | Depende del SRI real, que el simulador no mide; 30 min de cola son más de 3.000 facturas |
| `consumidor-detenido` | lag > 0 durante 10 min | Igual | El lag normal es 0 y no pasó de 6 |
| `conexiones-postgresql` | > 80 % | Igual | 20 en el pico y 50 saturado con 2 procesos; 4 procesos (144) sí la dispararían |
| `errores-5xx` | 2 % / 5 % | Igual | Ningún 5xx en las corridas de capacidad, salvo el defecto de §9.1 |
| Disco | 80 % / 90 % | Igual | Ver §11 |
| Navegador (`ui.error`, web vitals) | No existen | No existen | La carga por API no genera tráfico de navegador: S9.5 |

El resto no depende de la carga. Los valores son de referencia hasta tener el tráfico del piloto
(S9.5).

### 10.1 Comprobación en SigNoz

Con el SigNoz local (v0.151.0), las reglas sincronizadas y la telemetría de la copia encendida:

- `scripts/signoz.sh verify`: 50 consultas con datos, ninguna con error.
- `latencia-pos` disparó con 700 ventas/min pedidas (p95 de 5,1 s) y `rechazos-sri` con 5
  transiciones sintéticas a `rejected`.
- `facturas-atascadas` disparó con la cola que quedó de la rampa, como corresponde.

Esa corrida **no sirve para medir capacidad**: SigNoz en la misma Mac dejó la máquina sin recursos
(carga 66) y solo entraron 65 ventas por minuto. Sí mostró cómo falla el core asfixiado: el pool de
SQLAlchemy (5 + 10 por proceso) se agota y las solicitudes terminan en 500 tras 30 s, además de 502
en Caddy. En las demás corridas, hasta 900 ventas/min pedidas, no hubo ningún error del servidor.

No se midió cuánto cuesta la telemetría. Las corridas de capacidad incluyen la instrumentación de los
servicios, con el Collector descartándola, que es como está producción hoy.

## 11. Dimensionamiento del VPS

**Se mantiene: 4 vCPU, 8 GB de RAM y 80 GB de disco, con `CORE_WEB_CONCURRENCY=2`.**

- **CPU:** es lo primero que se agota. Aun si el VPS fuera 3 veces más lento por núcleo, quedarían unas
  200 ventas por minuto, 50 veces el pico del piloto.
- **Memoria:** unos 2,3 GB entre todos los contenedores bajo carga (core-api 480 MB de 768, PostgreSQL
  560 MB de 1,5 GB, Kafka 550 MB de 1 GB). Los límites se quedan como están. Un VPS de 4 GB no se
  midió y no deja margen.
- **Disco:** cada venta facturada ocupa unos 25 KB (core, facturación y comprobantes): unos 5 GB al
  año para el piloto. Kafka ocupó 1,6 GB con su retención de 7 días.

## 12. Pendientes

- Repetir la rampa, la API y la facturación en el primer VPS real.
- Ajustar los umbrales con el tráfico del piloto y crear las alertas del navegador (S9.5).
- Corregir la exportación de datos en faclab-infra (§9.2).
- Medir con muchas empresas en la misma base.
