# Análisis de brechas

> Base: [CURRENT_STATE.md](CURRENT_STATE.md) (auditoría del 2026-10-14). Leyenda de clasificación:
> **V** verificado, **P** parcialmente verificado, **PV** pendiente de validar.
>
> Prioridad:
> - **P0**: impide vender el sistema o pone en riesgo la integridad comercial, legal o el aislamiento
>   entre empresas.
> - **P1**: necesario antes del piloto con un cliente real.
> - **P2**: necesario antes de escalar a varios clientes.
> - **P3**: mejora recomendable.
>
> La columna **Sesión** remite a [ROADMAP.md](ROADMAP.md) y a `sessions/`.

## 1. Respuesta corta: ¿qué impide vender hoy?

1. **No hay multiempresa ni multisucursal** (G-01 a G-06). Cada cliente necesitaría su propia
   instalación y facturación solo admite un emisor con un contador global.
2. **La facturación no es confiable para producción** (G-07 a G-10): apunta al SRI de pruebas, pierde
   ventas de clientes sin email, puede repetir secuenciales y no guarda la autorización.
3. **El inventario del POS no respeta ubicaciones** y la caja es global (G-03, G-04).
4. **Faltan capacidades básicas de ferretería**: cantidades decimales, unidades con conversión, nota de
   crédito e importación de datos (sección 3).
5. **No hay forma segura de operar**: sin CI, sin imagen de producción segura, sin infraestructura,
   respaldos ni monitoreo desplegado (G-38, G-52 a G-58).

## 2. Hallazgos

### 2.1 Multiempresa y organización

| ID | Hallazgo | Clas. | Evidencia | Riesgo | Prio. | Sesión |
|---|---|---|---|---|---|---|
| G-01 | No existe tenant ni aislamiento lógico de datos | V | Búsqueda de tenant/company/branch sin resultados en `src`, `alembic` | Imposible ofrecer SaaS; acceso cruzado si se comparte la base | P0 | S2.1–S2.4 (S2.1 hecha: empresas, membresías, token con `tid` y administración de usuarios por empresa; S2.2 hecha: contexto de empresa en requests, mensajes y tareas, `SET LOCAL app.tenant_id`, repositorio base que asigna y filtra, `tenant_id` en eventos y outbox; S2.3 hecha: `tenant_id NOT NULL` en las 31 tablas de negocio, restricciones únicas y FKs compuestas por empresa, consultas propias filtradas y nueva línea base de migraciones; S2.4 hecha: RLS forzado en las 31 tablas de negocio, roles `faclab_owner`/`faclab_app`/`faclab_worker`, FKs compuestas en toda referencia que una ruta puede llenar y suite de aislamiento que recorre todas las rutas. **Cerrada**) |
| G-02 | No existen sucursales, establecimientos, puntos de emisión ni terminales | V | Modelos en `src/**/infra/models.py` | No se puede emitir desde varios establecimientos ni separar cajas | P0 | S2.5 (resuelta: sucursales, puntos de emisión y terminales en `src/organization/`, bodegas por sucursal, acceso por sucursal con `bids` y `X-Branch-Id`; el POS y sus ventas los usan desde S2.6; falta el frontend, S2.9) |
| G-03 | Un solo turno abierto en todo el sistema; cajero como texto libre | V | `src/pos/shift/app/commands/open_shift.py:32`, `src/pos/shift/infra/models.py:14-29` | Dos cajas no pueden operar a la vez; cierre de caja sin responsable | P0 | S2.6 (resuelta: turno por terminal con índice único parcial, abierto y cerrado por el usuario del token, `X-Terminal-Id`; el frontend lo envía en S2.9) |
| G-04 | El POS descuenta stock de una fila arbitraria y escribe movimientos sin ubicación | V | `confirm_sale.py:66,83`, `quick_sale.py:128,157`, `src/shared/infra/repositories.py:138-145` | Stock por bodega incorrecto; kárdex inconsistente | P0 | S2.6 (resuelta: ventas, cancelaciones y devoluciones del POS en la ubicación de la terminal, movimientos con ubicación y documento; ventas y devoluciones numeradas por sucursal) |
| G-05 | Facturación con un solo emisor y secuencial global | V | `faclab-invoicing/src/modules/company-config/domain/company-config.ts:11` | No admite más de un RUC ni varios puntos de emisión | P0 | S2.8 (resuelta: perfil fiscal, certificados, ambiente SRI y secuenciales por empresa; establecimiento y punto de emisión de cada venta en `sales.confirmed` v2; API filtrada por el `tid` del token; falta la pantalla de la web, S2.9) |
| G-06 | Restricciones únicas globales: SKU, código de barras, `tax_id` de clientes y proveedores, usuario, email, serie | V | `src/catalog/product/infra/models.py:31,33`, `src/customers/infra/models.py:16`, `src/auth/infra/models.py:14-17` | Dos empresas no podrían tener el mismo SKU o cliente | P0 | S2.3 (hecha: SKU, código de barras, símbolo de unidad, `tax_id` de clientes y proveedores, código de bodega, serie y número de orden de compra son únicos por empresa. Usuario y email siguen globales a propósito: identidad global, ADR-0003) |

### 2.2 Facturación electrónica

| ID | Hallazgo | Clas. | Evidencia | Riesgo | Prio. | Sesión |
|---|---|---|---|---|---|---|
| G-07 | Producción usa las URLs del SRI de pruebas (`celcer`) y el broker `localhost:29092` | V | `faclab-invoicing/src/config/production.ts:27-34` | Facturas "autorizadas" sin validez tributaria | P0 | S1.3 (resuelta: `SRI_ENVIRONMENT` elige `celcer` o `cel` y, como `KAFKA_BROKERS`, la región, las tablas y el bucket, es obligatoria en producción) |
| G-08 | El core envía `email`, `phone`, `address`, `sku` o `product_name` nulos y facturación los exige | V | `src/invoicing/infra/event_handlers.py:42-50`, `faclab-invoicing/.../schemas.ts:18-30` | La venta va a la cola de mensajes fallidos (DLQ, *dead letter queue*) y nunca se factura | P0 | S1.6 (resuelta: contrato v1 con esos campos nulables; invoicing los acepta y el XML los omite) |
| G-09 | Guardar la configuración del emisor lee y reescribe el contador: puede retroceder y repetir secuenciales; la primera factura sale con 000000002 | V | `company-config.commands.ts:40-46`, `dynamo-company-config.repository.ts:22-53` | Rechazo por secuencial duplicado; huecos | P0 | S2.7, S2.8 (parcial en S2.7: fila de `sequences` con `UPDATE ... RETURNING`, la primera factura es 000000001 y guardar la configuración sin `invoiceSequence` no toca el contador; resuelta en S2.8: secuencial por empresa, establecimiento, punto de emisión y tipo, tomado en la misma transacción que lo guarda en la factura, valor inicial que no retrocede (`SEQUENCE_CANNOT_GO_BACK`), `uq_invoices_tenant_number`; guardar el perfil nunca lo mueve) |
| G-10 | No se guarda número ni fecha de autorización ni el XML autorizado | V | `invoice.mapper.ts:29-55` | No se puede entregar ni conservar el comprobante autorizado | P0 | S4.1 |
| G-11 | No existe nota de crédito; `RefundCompleted` no tiene suscriptores | V | `src/pos/refund/app/commands/process_refund.py:112`, búsqueda de suscriptores sin resultados | Devoluciones sin respaldo tributario | P1 | S4.5 |
| G-12 | No hay RIDE (Representación Impresa del Documento Electrónico) ni envío por correo | V | Búsqueda sin resultados | El cliente final no recibe su comprobante | P1 | S4.4 |
| G-13 | Las llamadas SOAP al SRI (30 s de timeout) se hacen dentro del consumidor de Kafka | P | `faclab-invoicing/src/shared/infra/kafka.ts`, `soap-client.ts:16-25` | Un SRI lento frena la recepción de nuevas ventas | P1 | S4.2 |
| G-14 | El programador de recuperación asume una sola instancia (bloqueo en memoria) | V | `invoice-recovery.ts:24-29` | Doble envío si se escala a dos instancias | P2 | S4.2 |
| G-15 | La clave de acceso usa el `saleId` como código numérico de 8 dígitos | V | `access-code-generator.ts:16` | Falla con id > 99.999.999; código predecible | P2 | S4.1 |
| G-16 | `pagos` puede sumar más que `importeTotal` porque el core envía lo entregado, no lo aplicado | P | `quick_sale.py:137-180`, `generate_receipt.py:98` | Posible rechazo del SRI | P1 | S3.3, S4.1 |
| G-17 | No se escriben `contribuyenteEspecial`, `agenteRetencion` ni `contribuyenteRimpe` | V | `invoice-xml-builder.ts` (solo los mappers los leen) | XML incompleto para ciertos emisores | P1 | S4.1 |
| G-18 | Dos reenvíos simultáneos de la misma venta pueden crear dos facturas activas (consulta eventual al índice + condición solo sobre `id`) | P | `receive-sale.ts:36-44`, `dynamo-invoice.repository.ts:35` | Doble facturación | P2 | S2.7 (resuelta: índice único parcial `uq_invoices_active_sale`; `createInvoice` devuelve `false` y el reenvío se descarta; prueba con reenvíos en paralelo) |
| G-19 | No hay validación local contra el XSD | V | No hay XSD en el repo | Rechazos que se descubren recién en el SRI | P2 | S4.1 |
| G-20 | Se puede cancelar una venta CONFIRMED mientras su factura está en curso; la autorización posterior solo se registra | P | `src/sales/domain/entities.py:111-115`, `invoice_messages.py:36-66` | Factura autorizada de una venta anulada | P1 | S3.3, S4.5 |
| G-21 | `InvoiceRejected` solo se registra; la venta no refleja el estado de facturación | V | `src/invoicing/infra/invoice_messages.py:36-42` | Operadores no ven qué ventas necesitan acción | P1 | S3.4, S4.3 |
| G-22 | Normativa 2026 (transmisión inmediata, plazo de anulación con aceptación del receptor, restricciones para consumidor final) no está modelada | PV | Sección 4 | Sanciones o comprobantes no anulables | P1 | S4.1, S4.5 |
| G-23 | No se valida que el certificado corresponda al RUC; no hay alerta de vencimiento | V | `certificate.commands.ts:27-29`, `issuer-readiness.ts:176-191` | Firmas inválidas; facturación detenida por certificado vencido | P2 | S2.8, S7.2 (resuelta en S2.8 la validación: el certificado debe nombrar el RUC del emisor o la cédula de una persona natural, al subirlo y al seleccionarlo; se guarda su vencimiento y el readiness avisa 30 días antes. Falta la alerta de vencimiento, S7.2) |

### 2.3 Integridad transaccional

| ID | Hallazgo | Clas. | Evidencia | Riesgo | Prio. | Sesión |
|---|---|---|---|---|---|---|
| G-24 | El relay del outbox se detiene en el primer fallo, sin máximo de intentos ni estado final | V | `src/shared/infra/outbox/relay.py:86-102` | Un mensaje dañado bloquea toda la facturación | P0 | S3.4 |
| G-25 | El consumidor del core reintenta cada 5 s para siempre | V | `src/shared/infra/kafka/consumer.py:102-106` | Partición bloqueada | P1 | S3.4 |
| G-26 | Ningún POST acepta `Idempotency-Key` | V | Búsqueda sin resultados | Un reintento del POS duplica la venta y el descuento de stock | P1 | S3.1 |
| G-27 | Un movimiento OUT sin fila de stock crea stock negativo | V | `src/inventory/stock/infra/event_handlers.py:50-61` | Stock negativo silencioso | P1 | S3.2 |
| G-28 | La disponibilidad del POS usa `quantity` en vez de `available_quantity` | V | `confirm_sale.py:67`, `src/inventory/stock/domain/entities.py:15-17` | Se vende stock reservado para transferencias | P2 | S3.2 |
| G-29 | Los ajustes aplican la diferencia calculada al agregar el ítem, no al confirmar | V | `src/inventory/adjustment/app/commands/adjustment.py:161-175,222-226` | Deriva de stock | P2 | S3.2 |
| G-30 | Se pueden registrar pagos en ventas canceladas; `/confirm` del POS no exige cobertura | V | `src/sales/app/commands/register_payment.py:38-70`, `src/sales/domain/entities.py:104-109` | Caja descuadrada | P1 | S3.3 |
| G-31 | Dinero `Numeric(12,6)`: tope 999.999,99 por campo; JSON como `float` | V | `src/shared/infra/precision.py:5-10`, `src/shared/infra/validators.py:7-10` | Error en totales grandes (compras, reportes) | P1 | S3.3 |
| G-32 | Una venta con dos líneas del mismo producto valida stock por línea | P | Revisión de octubre 2026 | Sobreventa | P2 | S3.2 |
| G-33 | Número de orden de compra con `MAX()` sin reintento | V | `src/purchasing/infra/repositories.py:45-54` | 409 en creación concurrente | P3 | S3.3 |
| G-34 | Handlers de ventas de administración que nunca se ejecutan; las ventas de administración no se confirman ni cancelan | V | `src/inventory/infra/event_handlers.py:22-121`, `src/sales/infra/routes.py:52-86` | Código muerto; ventas a crédito imposibles | P2 | S5.5 |
| G-35 | Relay, productor y consumidor como hilos dentro del proceso del API | V | `main.py:80-110` | Escalar el API multiplica hilos; un fallo del API detiene la mensajería | P2 | S3.4 |
| G-36 | `OrSpecification.to_query_criteria` mezcla criterios con `or_(*left, *right)` | V | `src/shared/domain/specifications.py:49-54` | Filtros incorrectos cuando un lado tiene varias condiciones | P2 | S3.2 |
| G-37 | IVA de órdenes de compra fijo en 0 | V | `src/purchasing/domain/entities.py:66` | Costos y reportes de compra incorrectos | P1 | S5.7 |

### 2.4 Seguridad

| ID | Hallazgo | Clas. | Evidencia | Riesgo | Prio. | Sesión |
|---|---|---|---|---|---|---|
| G-38 | No hay `.dockerignore` y el Dockerfile hace `COPY . .` | V | `Dockerfile:24,33` | `.env`, `.venv`, `.git` y datos de Postgres dentro de la imagen | P0 | S1.2 (resuelta: `.dockerignore` e imagen de producción con copia explícita) |
| G-39 | Campos de actor tomados del cuerpo de la solicitud | V | `src/pos/sales/infra/validators.py:69-73`, `src/pos/cash/infra/validators.py:16-20`, `src/pos/refund/infra/validators.py:37-41` | Suplantación en caja, devoluciones y ajustes | P0 | S1.4 (resuelta: turnos, ventas POS, caja, devoluciones, ajustes y transferencias toman el autor del token; nombre completo del usuario o su username) |
| G-40 | `DOCS_ENABLED` activo por defecto en producción | V | `config/base.py:73` | Exposición del contrato interno | P1 | S1.2 (resuelta: falso por defecto fuera de local; también apaga `/openapi.json`) |
| G-41 | CORS fijo en código | V | `main.py:70` | No se puede desplegar el frontend en otro dominio | P1 | S1.2 (resuelta: `CORS_ORIGINS`, obligatoria fuera de local) |
| G-42 | Sin límite de intentos de login ni rate limiting | V | Búsqueda sin resultados | Fuerza bruta | P1 | S1.4 (resuelta para el login: bloqueo por usuario e IP, `LOGIN_LOCKED`), S6.3 (límite general del API) |
| G-43 | El refresh token no rota ni detecta reutilización | V | `src/auth/app/commands/refresh_token.py:32-51` | Un refresh robado sirve durante 7 días | P1 | S1.4 (resuelta: rota en cada refresh; reutilizarlo revoca la sesión, `TOKEN_REUSED`) |
| G-44 | Tokens (incluido el refresh) en `localStorage` | V | `faclab-web/src/shared/lib/auth/tokenStorage.ts` | Robo de tokens mediante inyección de scripts (XSS) | P2 | S1.4 (resuelta: refresh en cookie HttpOnly `SameSite=Strict`, access token en memoria) |
| G-45 | Textos internos de `ValueError` y PyJWT en las respuestas | V | `src/shared/infra/middlewares.py:188-195`, `token_service.py:80` | Fuga de detalles internos | P2 | S1.4 (resuelta: mensajes genéricos con código estable; el detalle solo va al log) |
| G-46 | El log de validación puede incluir una contraseña en texto plano | P | `src/shared/infra/middlewares.py:127` | Credenciales en logs | P1 | S1.4 (resuelta: el log de validación no incluye `input` y hay redacción mínima de claves sensibles), S1.5 (resuelta: lista bloqueada completa de OBSERVABILITY.md §4.6) |
| G-47 | Login sin hash para usuarios inexistentes (enumeración por tiempo) | P | `src/auth/app/commands/login.py:39-43` | Enumeración de usuarios | P3 | S1.4 (resuelta: hash ficticio para usuarios inexistentes; también se bloquean) |
| G-48 | Invoicing comparte el secreto HS256 y puede emitir tokens para el core | V | `faclab-invoicing/src/shared/infra/http/auth.ts:45-109` | Un compromiso de invoicing compromete todo | P2 | S6.1 |
| G-49 | Kafka sin TLS ni SASL; kafka-ui sin autenticación | V | `faclab-infra/docker-compose.yml` | Aceptable solo en red privada | P2 | S8.1 |
| G-50 | No hay bitácora de auditoría | V | Búsqueda sin resultados | Sin trazabilidad de cambios de precio, ajustes, caja y usuarios | P1 | S3.5 |
| G-51 | `scripts/seed.py` borra tablas sin verificar el entorno | V | `scripts/seed.py:79-82` | Borrado accidental en un entorno real | P2 | S1.2 (resuelta: solo corre con `ENVIRONMENT=local`) |
| G-52 | El secreto de SigNoz en el compose de ejemplo es el valor por defecto del proyecto | V | `Telemetry/deploy/docker/docker-compose.yaml:122` | Acceso no autorizado al panel de observabilidad | P1 | S8.6 |

### 2.5 Operación, entrega y versiones

| ID | Hallazgo | Clas. | Evidencia | Riesgo | Prio. | Sesión |
|---|---|---|---|---|---|---|
| G-53 | Ningún repositorio tiene CI | V | Solo `.github/pull_request_template.md` | Regresiones sin detectar | P0 | S1.1 (resuelta: CI en los cuatro repos) |
| G-54 | Healthcheck roto (`curl` no existe) y sin endpoints de salud | V | `docker inspect`, `docker-compose.yml:17-22`, `main.py:409-411` | Orquestador sin señal de salud | P1 | S1.2 (resuelta: `/health/live`, `/health/ready` y healthchecks sin curl) |
| G-55 | Imagen de producción como root, con herramientas de compilación y un solo proceso | V | `Dockerfile:31-37` | Superficie de ataque y capacidad limitada | P1 | S1.2 (resuelta: imagen sin compiladores, usuario `app`, `WEB_CONCURRENCY` workers) |
| G-56 | Invoicing y web sin Dockerfile; `package-lock.json` de invoicing ignorado; dependencia `pettier` | V | `faclab-invoicing/.gitignore:4`, `package.json:68` | Builds no reproducibles | P1 | S1.1 (lock versionado y sin `pettier`) y S1.3 (resuelta: Dockerfiles de invoicing y web, construidos en CI) |
| G-57 | Sin tags ni versionado coordinado entre repos | V | `git tag` vacío en los cuatro | Despliegues incompatibles | P2 | S8.2 |
| G-58 | PostgreSQL 14 llega al fin de soporte el 12/11/2026 | V | `docker-compose.yml`, política de versiones de PostgreSQL | Sin parches de seguridad | P1 | S1.2 (resuelta: compose local y CI en PostgreSQL 17) |
| G-59 | Sin infraestructura de producción, respaldos ni plan de recuperación | V | No hay manifiestos en ningún repo | Pérdida de datos tributarios | P0 (antes del piloto) | S8.1, S8.3 |
| G-60 | `.venv` en Python 3.11 y Docker en 3.12; passlib sin mantenimiento (usa `crypt`, eliminado en 3.13) | V | Advertencia de pytest | Bloqueo para actualizar Python | P3 | S1.1 (parcial: CI en 3.12; falta el `.venv` local), S1.4 |

### 2.6 Observabilidad

| ID | Hallazgo | Clas. | Evidencia | Riesgo | Prio. | Sesión |
|---|---|---|---|---|---|---|
| G-61 | El middleware de OTel queda dentro del de errores: logs HTTP sin `trace_id`; errores de dominio marcan el span como error | V | `main.py:227` vs `:360-368` | No se correlacionan logs y trazas; tasa de error inflada | P1 | S1.5 (resuelta: el middleware de OTel se agrega al final y queda por fuera; un 404 de dominio deja el span sin error y con `http.response.status_code`) |
| G-62 | El procesador que agrega `trace_id` a los logs nunca se ejecuta | V | `src/shared/infra/logging.py:42-49` | Ídem | P1 | S1.5 (resuelta: `add_trace_context` lee el span activo; cada log lleva `trace_id`, `span_id`, `http.request.id` y `event.name`) |
| G-63 | Probablemente no hay spans de consultas SQL | P | `src/shared/infra/database.py:3`, `main.py:46` | Sin visibilidad de la base | P2 | S1.5 (resuelta: se instrumenta el engine de los requests; las consultas del relay y del readiness no inician trazas) |
| G-64 | Sin `service.version`; sampler no *parent-based*; exportador sin TLS fijo | V | `src/shared/infra/adapters/telemetry.py:39-58` | Trazas cortadas entre servicios; sin comparación por versión | P2 | S1.5 (resuelta: `service.version` desde `SERVICE_VERSION`, `service.namespace`, `deployment.environment.name`, sampler `ParentBased` y TLS con `OTEL_EXPORTER_OTLP_INSECURE`) |
| G-65 | Errores de dominio registrados como ERROR | V | `src/shared/app/commands.py` | Ruido que tapa errores reales | P2 | S1.5 (resuelta: comandos, consultas y handlers de eventos registran los errores de dominio como WARN sin marcar el span; `handler.errors` separa `error.kind`) |
| G-66 | Sin redacción de datos sensibles en logs (core e invoicing) | V | `logging.py`, `faclab-invoicing/src/shared/logger.ts` | Fuga de datos personales o credenciales | P1 | S1.5 (resuelta: lista bloqueada de §4.6 en structlog y en pino, a cualquier profundidad; falta enmascarar cédula, RUC y email) |
| G-67 | Spans de Kafka sin convenciones semánticas; span del productor de invoicing huérfano; invoicing no vacía telemetría al apagar | V | `producer.py:96-111`, `kafka-producer.ts:25-35`, `server.ts:30` | Trazas incompletas | P2 | S1.5 (resuelta: `send <tópico>` y `process <tópico>` con atributos `messaging.*` en core e invoicing; el relay continúa la traza del request; invoicing vacía la telemetría al salir) |
| G-68 | Sin métricas de negocio ni de cola (outbox pendiente, edad, facturas pendientes, latencia del SRI por operación) | V | `telemetry_instruments.py`, `metrics.ts` | Los problemas los reportan los clientes | P1 | S7.1, S7.2 |
| G-69 | Frontend sin telemetría | V | Búsqueda sin resultados | Errores de interfaz invisibles | P2 | S7.3 |
| G-70 | SigNoz no desplegado; sin dashboards ni alertas versionados | V | `deploy/common/dashboards/.gitkeep` | Sin detección temprana | P1 | S7.5, S8.6 |
| G-71 | `x-request-id` del cliente aceptado sin validar y no devuelto en la respuesta | V | `src/shared/infra/middlewares.py:152` | Inyección en logs; correlación difícil | P3 | S1.5 (resuelta: `RequestIdMiddleware` valida el UUID o genera uno, lo devuelve y lo agrega a logs y span) |

### 2.7 API e integraciones

| ID | Hallazgo | Clas. | Evidencia | Riesgo | Prio. | Sesión |
|---|---|---|---|---|---|---|
| G-72 | No hay API versionada, credenciales de integración, scopes ni webhooks | V | `main.py:237-344` | Integraciones acopladas al contrato interno del frontend | P1 | S6.1–S6.5 |
| G-73 | Listados sin orden estable ni parámetros de ordenamiento | V | `src/shared/infra/repositories.py:138-177` | Paginación inconsistente | P2 | S6.3 |
| G-74 | `GET /api/invoices` de invoicing recorre toda la tabla | V | `dynamo-invoice.repository.ts:84-95` | Degradación con volumen | P2 | S2.7 (resuelta: `GET /api/invoices` paginado con `limit`/`offset`, filtros e índices; `meta.pagination` con el total; faclab-web pagina en el servidor) |

### 2.8 Pruebas

| ID | Hallazgo | Clas. | Evidencia | Riesgo | Prio. | Sesión |
|---|---|---|---|---|---|---|
| G-75 | Invoicing tiene 31 pruebas y ninguna cubre XML, firma, SOAP, Kafka, JWT ni persistencia | V | `vitest run` | Regresiones tributarias sin detectar | P1 | S1.1, S4.1, S4.2 |
| G-76 | No hay pruebas de contrato entre servicios | V | — | Incompatibilidades como G-08 | P0 | S1.6 (resuelta: JSON Schema versionado en `contracts/`, pruebas de contrato en el CI de core e invoicing) |
| G-77 | No hay E2E contra servicios reales ni pruebas de carga | V | — | Sin línea base para umbrales | P2 | S9.1, S9.2 |
| G-78 | Cobertura del core desconocida (último `.coverage` de abril 2026, ~66,8 %) | P | `.coverage` | — | P3 | S1.1 (resuelta: 95 %, medida en cada run de CI) |

## 3. Requisitos de ferretería

| ID | Capacidad | Estado | Primer cliente | Sesión |
|---|---|---|---|---|
| F-01 | Cantidades decimales (metros de cable, kilos de clavos) | No existe (enteros en todas las tablas) | **Imprescindible** | S5.1 |
| F-02 | Unidades con conversión y presentaciones (unidad, paquete, caja, rollo; compra en caja, venta por unidad) | No existe (una unidad sin conversión por producto) | **Imprescindible** | S5.2 |
| F-03 | Código de barras por presentación | Uno por producto | Imprescindible | S5.2 |
| F-04 | Nota de crédito electrónica para devoluciones | No existe | **Imprescindible** | S4.5 |
| F-05 | Importación masiva de productos, clientes, proveedores y saldos iniciales | No existe | **Imprescindible** (catálogos de miles de artículos) | S5.8 |
| F-06 | Listas de precios minorista y mayorista, precio por volumen | Un solo `sale_price` | Muy recomendable | S5.3 |
| F-07 | Cotizaciones con vigencia y conversión a venta | No existe | Muy recomendable | S5.4 |
| F-08 | Venta a crédito, abonos, estado de cuenta, antigüedad de saldos, límite de crédito | Solo pagos parciales | Muy recomendable | S5.5 |
| F-09 | Costo promedio ponderado y kárdex valorizado por bodega | No existe (el reporte llama "costo promedio" al precio de compra) | Muy recomendable | S5.6 |
| F-10 | Cierre de caja numerado e inmutable con arqueo | Z calculado al consultar | Muy recomendable | S5.9 |
| F-11 | Devoluciones a proveedor | No existe | Puede esperar | S5.7 |
| F-12 | Cuentas por pagar | No existe | Puede esperar | S5.7 (básico) |
| F-13 | Variantes de producto | No existe | Puede esperar (se usan SKU separados) | — |
| F-14 | Guía de remisión (entregas a obra) y comprobante de retención | No existe | Depende del cliente piloto (PV) | Posterior a la Etapa 9 |
| F-15 | Transferencias, ajustes, lotes, series, stock por ubicación | Existe | — | — |
| F-16 | Bitácora de cambios de precio, ajustes y caja | No existe | Muy recomendable | S3.5 |

## 4. Cumplimiento SRI

| Tema | Estado | Clas. | Acción |
|---|---|---|---|
| Ficha técnica de comprobantes electrónicos, esquema offline | El SRI publica la versión 2.34 (julio 2026) | V (sitio del SRI) | Revisar cambios desde la 2.26 en S4.1 |
| Versión del XML de factura | Se usa 1.1.0; el SRI publica XSD 1.0.0, 1.1.0, 2.0.0 y 2.1.0 | V | Mantener 1.1.0 o subir a 2.1.0 si el cliente necesita detalles adicionales (decisión en S4.1) |
| Nota de crédito | El SRI publica XSD 1.0.0 y 1.1.0; no implementada | V | S4.5 |
| Resoluciones NAC-DGERCGC25-00000014 y NAC-DGERCGC25-00000017 (anulación de comprobantes) | Publicadas en el sitio del SRI | V (existencia) | Leer el texto oficial antes de S4.5 |
| Transmisión inmediata: la fecha de emisión debe coincidir con la fecha de la operación (desde 2026) | Fuentes secundarias | PV | Confirmar con el contador. Afecta la decisión vigente de usar la fecha de preparación para facturas tardías |
| Anulación hasta el día 7 (o 10, según la fuente) del mes siguiente y con aceptación del receptor | Fuentes secundarias contradictorias | PV | Confirmar en la resolución |
| Facturas a consumidor final no anulables ni con nota de crédito (desde 2026) | Fuentes secundarias | PV | Define el flujo de devoluciones del POS (S4.5) |
| Límite de monto para facturas a consumidor final | No se controla | PV (valor vigente) | S4.1 |
| Conservación de comprobantes autorizados durante el plazo legal | No se guarda el XML autorizado | V (falta) / PV (plazo) | S4.1, S8.3 |
| Ambiente de pruebas o producción por emisor | URLs fijas en pruebas | V | S1.3, S2.8 (resuelta en S2.8: el ambiente del emisor elige los servicios del SRI; solo `NODE_ENV=production` llega a producción) |

## 5. Riesgos, costos y decisiones pendientes

### 5.1 Riesgos principales antes de escalar

| Riesgo | Mitigación |
|---|---|
| El cambio multiempresa toca las 34 tablas y casi todos los handlers | Hacerlo antes de tener datos productivos (hoy no los hay), con CI (S1.1), RLS (S2.4) y pruebas negativas de aislamiento |
| Kafka en un solo nodo con replicación 1 | El outbox conserva los mensajes publicados N días para poder reenviarlos (S3.4); respaldo del volumen; aceptar para el piloto |
| SigNoz consume mucha memoria (ClickHouse) | VPS separado o servicio administrado (decisión D-1) |
| Cambios normativos del SRI | Verificación periódica de la ficha técnica; pruebas con XSD (S4.1) |
| Un solo desarrollador y cuatro repositorios | Contratos versionados y pruebas de contrato (S1.6), versionado coordinado (S8.2) |

### 5.2 Costos operativos (estimaciones de dimensionamiento, sin precios)

- **VPS de aplicación** (piloto): 4 vCPU y 8 GB de RAM para core (API y worker), invoicing, PostgreSQL,
  Kafka y Caddy. PV: medir en S9.2.
- **VPS de observabilidad**: SigNoz autogestionado necesita al menos 4 GB; guías de terceros recomiendan
  8 GB para producción pequeña y 16 GB o más con más volumen. PV.
- **Almacenamiento de objetos** compatible con S3 para XML y RIDE, con respaldo fuera del servidor.
- **Correo transaccional** para enviar el RIDE.
- **Certificados de firma** los aporta cada cliente.

### 5.3 Decisiones pendientes

| ID | Decisión | Quién | Cuándo |
|---|---|---|---|
| D-1 | SigNoz autogestionado en un VPS separado o SigNoz Cloud | Usuario (costo) | Antes de S8.6 |
| D-2 | Proveedor de almacenamiento de objetos (externo compatible con S3 o disco local con respaldo) | Usuario | Antes de S4.1 |
| D-3 | Proveedor de correo transaccional | Usuario | Antes de S4.4 |
| D-4 | Fecha de emisión de facturas tardías, plazos de anulación y reglas de consumidor final | Contador | Antes de S4.1 y S4.5 |
| D-5 | Planes, precios y límites de la suscripción | Usuario | Antes de S8.4 |
| D-6 | Almacén para límites de solicitudes de la API pública (Redis o PostgreSQL) | Técnica | En S6.3 |
| D-7 | Retención de logs, trazas y métricas | Usuario (costo) | Antes de S8.6 |
| D-8 | Documentos SRI adicionales (retención, guía de remisión) según el cliente piloto | Usuario | Antes de S9.4 |
| D-9 | Dominio y subdominios (aplicación, API, documentación) | Usuario | Antes de S8.1 |
