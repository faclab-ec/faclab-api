# Arquitectura

> Este documento describe los patrones internos del core. La auditoría del ecosistema (core,
> facturación, frontend, Kafka y observabilidad), la arquitectura objetivo SaaS y el roadmap están en
> [docs/architecture/](architecture/README.md).

## Clean Architecture

El proyecto organiza el codigo en tres capas con dependencias unidireccionales:

```
┌─────────────────────────────────────────┐
│             Domain Layer                │
│  Entities · Value Objects · Events      │
│  Specifications · Exceptions            │
│  (sin dependencias externas)            │
└──────────────────┬──────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│           Application Layer             │
│  CommandHandler · QueryHandler          │
│  Repository interface · EventBus iface  │
│  (depende solo del Domain)              │
└──────────────────┬──────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│         Infrastructure Layer            │
│  FastAPI Routes · SQLAlchemy Models     │
│  Mappers · Repositories · EventBus      │
│  Middleware · Telemetry                 │
│  (implementa las interfaces del Domain) │
└─────────────────────────────────────────┘
```

**Reglas de dependencia:**
- El Domain no importa nada del Application ni de Infrastructure
- El Application solo importa del Domain
- La Infrastructure puede importar de todas las capas, pero nunca al reves

## CQRS

Cada modulo separa las operaciones de escritura y lectura en handlers independientes:

### Commands (escritura)

```python
@dataclass
class CreateProductCommand(Command):
    name: str
    sku: str
    category_id: int

class CreateProductHandler(CommandHandler[CreateProductCommand, ProductOutput]):
    def __init__(self, repo: Repository[Product]):
        self._repo = repo

    async def execute(self, cmd: CreateProductCommand) -> ProductOutput:
        product = Product(name=cmd.name, sku=cmd.sku, ...)
        await self._repo.create(product)
        return ProductOutput(...)
```

### Queries (lectura)

```python
@dataclass
class GetProductByIdQuery(Query):
    id: int

class GetProductByIdHandler(QueryHandler[GetProductByIdQuery, ProductOutput]):
    async def execute(self, query: GetProductByIdQuery) -> ProductOutput:
        product = await self._repo.get_by_id(query.id)
        return ProductOutput(...)
```

Cada handler recibe automaticamente:
- Un span de OpenTelemetry
- Metricas (histograma de duracion + contador de invocaciones/errores)
- Log estructurado con structlog

## Patrones de Diseno

### Repository Pattern

`SqlAlchemyRepository[E]` en `src/shared/infra/repositories.py` provee:

- CRUD: `create()`, `update()`, `delete()`, `get_by_id()`, `get_all()`
- Filtrado: `filter()`, `filter_by()`, `filter_by_spec()`
- Paginacion: `limit`, `offset`
- Ordenamiento: `order_by`, `desc_order`
- Conteo: `count_by_spec()`

Los repositorios concretos solo declaran `__model__`:

```python
class ProductRepository(SqlAlchemyRepository[Product]):
    __model__ = ProductModel
```

Si el modelo declara `__tenant_scoped__ = True` (y tiene la columna `tenant_id`), el repositorio base trabaja
solo en la empresa del contexto: ver [Contexto de empresa](#contexto-de-empresa).

### Mapper Pattern

`Mapper[E, M]` en `src/shared/infra/mappers.py` mapea por convencion entre entidades de dominio y modelos SQLAlchemy usando introspeccion:

- Mapea campos por nombre automaticamente
- Detecta campos Enum via `get_type_hints()`
- Los mappers concretos solo declaran `__entity__` y `__exclude_fields__`

```python
@injectable(lifetime=Lifetime.SINGLETON)
class ProductMapper(Mapper[Product, ProductModel]):
    __entity__ = Product
    __exclude_fields__ = frozenset({"created_at"})
```

### Domain Events

Comunicacion entre modulos a traves de `EventBus.publish()`. Los event handlers se registran con el decorador `@event_handler()` y se ejecutan en scopes separados de wireup:

```
SaleConfirmed          → Movement(OUT) por cada item → Stock decrementado
SaleCancelled          → Movement(IN) por cada item  → Stock restaurado
PurchaseOrderReceived  → Movement(IN) por cada item  → Stock incrementado
MovementCreated        → Stock actualiza cantidades
LotCreated/Updated     → Serial numbers actualizados
```

```python
@event_handler(SaleConfirmed)
async def on_sale_confirmed(event: SaleConfirmed, repo: ...) -> None:
    for item in event.items:
        await create_out_movement(item, ...)
```

### Outbox de Kafka

Los mensajes hacia otros servicios no se publican desde el handler: `OutboxWriter.add()` los guarda en la tabla `outbox_messages` dentro de la misma transacción del request, junto con el contexto de traza. Si la transacción se revierte, el mensaje desaparece con ella. `OutboxRelay` publica los mensajes confirmados con la empresa del mensaje como clave (los de una empresa van por la misma partición) y el header `faclab-tenant-id`. Corre en el proceso worker (ver [Worker](#worker)) y revisa el outbox cada `OUTBOX_POLL_INTERVAL_SECONDS` (1 s). Con `RUN_BACKGROUND=true` corre también en el API, donde además se despierta tras cada commit que escribió un mensaje.

Cada mensaje tiene un estado: `pending`, `published` o `failed` (S3.4).

- **Orden por empresa, no global** (ADR-0005). Cada lote toma un advisory lock de su transacción, así que publica un solo relay a la vez aunque convivan el API y el worker durante un despliegue. Los mensajes de cada empresa salen por `id`.
- **Un mensaje que falla espera su próximo intento** (`next_attempt_at`) con backoff exponencial (`OUTBOX_RETRY_BASE_SECONDS` · 2^(n-1), con tope `OUTBOX_RETRY_MAX_SECONDS`). Mientras tanto frena solo a los siguientes de su empresa: los de las demás empresas se publican igual.
- **Tras `OUTBOX_MAX_ATTEMPTS` (10) queda `failed`**, se registra un log ERROR `outbox_message_failed` con el comando para reprocesarlo, y deja de frenar a su empresa. Se vuelve a encolar con `make outbox-retry` (ver [Mensajes atascados](#mensajes-atascados)).
- **Si el que falla es el broker**, el lote se corta sin contar el intento: una caída de Kafka no deja mensajes sanos en `failed`. `KafkaEventProducer` traduce a `BrokerUnavailableError` el productor sin conectar, los timeouts y los errores que aiokafka marca como reintentables.
- **Los publicados se purgan** después de `OUTBOX_RETENTION_DAYS` (14); los `failed` y `pending` se conservan.

Hoy el único mensaje es `sales.confirmed` para faclab-invoicing; lo arma `src/invoicing/infra/event_handlers.py` con la empresa que emite y su RUC, el establecimiento, la dirección y el punto de emisión de la venta, y los datos del cliente y los productos. Cada ítem lleva además `invoice_discount`, `invoice_base` e `invoice_tax`: sus montos en la factura del SRI, redondeados a centavos y con el descuento global ya prorrateado (`invoice_lines` en `src/sales/domain/services.py`). Las bases suman `subtotal - descuento` y bases más IVA suman el total cobrado, así que faclab-invoicing los copia al XML sin recalcular nada.

La forma de cada mensaje es un contrato versionado en `contracts/events/` (JSON Schema y ejemplos; ver [`contracts/README.md`](../contracts/README.md)). `sales.confirmed` lleva `schema_version: 2` (desde S2.8, con `tenant_id` y el punto de emisión; la historia está en `contracts/CHANGELOG.md`); la dirección del establecimiento puede ser `null`, el cliente puede venir sin email, teléfono ni dirección y un ítem sin `sku` ni `product_name`, siempre como `null`. `tests/contract` valida contra el esquema lo que este handler guarda en el outbox, y faclab-invoicing prueba su consumidor con los mismos ejemplos, copiados y fijados a un commit del core. Un cambio incompatible sube `schema_version` y se despliega primero en el consumidor.

### Consumidor de Kafka

`KafkaMessageConsumer` (`src/shared/infra/kafka/consumer.py`) corre en el worker (o en el API con `RUN_BACKGROUND=true`), con el consumer group `KAFKA_CONSUMER_GROUP_ID` (por defecto `faclab-core`). Entrega cada mensaje al handler de su topic y confirma el offset cuando el handler termina bien, así que los handlers deben ser idempotentes. Un mensaje que no es JSON se descarta. Si Kafka no está disponible, el consumidor y el productor reintentan la conexión en vez de morir.

Si el handler falla, el mensaje se reintenta con backoff (`KAFKA_CONSUMER_RETRY_BASE_SECONDS` · 2^(n-1), con tope de un minuto) sin pasar al siguiente de la partición. La espera es un `asyncio.sleep`, que no detiene el heartbeat del grupo. Al llegar a `KAFKA_CONSUMER_MAX_ATTEMPTS` (5), el mensaje se guarda en la tabla `dead_letters` con su tópico, partición, offset, clave, headers, valor, empresa y error, y se confirma su offset: la partición sigue. Una dead letter se guarda una vez por mensaje (`uq_dead_letters_message`), aunque llegue de nuevo. Si tampoco se puede guardar (la base caída), el offset no se confirma y el consumidor vuelve a él: el mensaje no se pierde. `dead_letters` es de infraestructura, como el outbox: sin RLS, y solo faclab_worker puede leerla y escribirla.

Hoy lee el topic `invoices`, donde faclab-invoicing publica cada transición de sus facturas (created → signed → sent → authorized / rejected). `src/invoicing/infra/invoice_messages.py` actúa ante `InvoiceAuthorized` (la venta pasa de `CONFIRMED` a `INVOICED`, su factura a `AUTHORIZED` con su id, y se publica `SaleInvoiced`) y ante `InvoiceRejected`. En ese caso, la factura pendiente pasa a `REJECTED` con su id y el motivo del SRI (`reason`). Un rechazo de la factura que ya se rechazó, repetido después de un reenvío, se ignora. Si la venta ya estaba facturada no hace nada; si no existe o ya no está confirmada (p. ej. se anuló antes de que el SRI respondiera), lo registra como error y sigue, porque eso se resuelve con una nota de crédito y no reintentando. Lee los mensajes según `contracts/events/invoices/v1.schema.json`: uno sin `schema_version` es v1 y uno de una versión que no conoce se registra (`invoice_message_unsupported_version`) y se descarta. La venta se busca en la empresa del header `faclab-tenant-id`; un mensaje sin empresa se registra (`invoice_message_without_tenant`) y se descarta.

### Worker

`worker.py` es la misma imagen que el API con otro comando (ADR-0007). Arranca la mensajería (productor, relay y consumidor, con `KAFKA_ENABLED`) y corre las purgas cada `WORKER_PURGE_INTERVAL_SECONDS` (una hora): los mensajes publicados del outbox, las claves de idempotencia (`IDEMPOTENCY_KEY_RETENTION_HOURS`) y las sesiones revocadas o vencidas (`AUTH_SESSION_RETENTION_DAYS`). Todas trabajan como faclab_worker en todas las empresas y son DELETE idempotentes, así que dos workers solo repiten trabajo.

- Con SIGTERM termina la tarea en curso y se detiene en orden: consumidor, relay, productor y OpenTelemetry. Su `service.name` es `faclab-core-worker`.
- `WorkerHealth` guarda el último ciclo exitoso de cada tarea (el relay y el consumidor reportan cada vuelta) en `WORKER_HEALTH_FILE`. `python -m src.shared.infra.worker.health` falla si el archivo no se actualizó en un minuto o si una tarea pasó su `max_age` sin un ciclo exitoso: es el healthcheck del servicio `worker`.
- El API arranca la mensajería solo con `RUN_BACKGROUND=true` (por defecto, para volver atrás), y entonces su readiness informa el productor. `docker-compose.yml` levanta el servicio `worker` y pone `RUN_BACKGROUND=false` en el API.
- La composición (los handlers de cada tópico, `create_messaging()`, las tareas) vive en `src/background/`, porque importa módulos.

### Mensajes atascados

Hasta que exista el rol de plataforma (S8.5), un CLI corre como faclab_worker sobre todas las empresas:

| Comando | Qué hace |
|---|---|
| `make outbox-failed` | Lista los mensajes `failed` del outbox, con su empresa, intentos y último error |
| `make outbox-retry ids="1 2" by=<quién>` (o `ids=--all`) | Los devuelve a `pending` con los intentos en cero; el relay los publica en su próxima vuelta |
| `make dead-letters` | Lista las dead letters pendientes |
| `make reprocess-dead-letter id=<id> by=<quién>` | Entrega el mensaje otra vez al handler de su tópico, en su empresa; si funciona queda `reprocessed`, si no suma un intento y el error |

Cada uno es `python -m src.background.cli <comando>`. `--by` es obligatorio y queda en la fila (`retried_by`/`retried_at`, `reprocessed_by`/`reprocessed_at`) y en el log (`outbox_message_retried`, `dead_letter_reprocessed`).

### Specification Pattern

Consultas reutilizables y componibles:

```python
# Composicion con operadores
spec = ActiveCustomers() & CustomersByType("WHOLESALE")
customers = await repo.filter_by_spec(spec)

# Negacion
spec = ~InactiveSuppliers()

# OR
spec = LowStockItems() | CriticalStockItems()
```

Cada Specification implementa:
- `is_satisfied_by(entity)` — evaluacion en memoria
- `to_query_criteria()` — traduccion a clausula SQLAlchemy WHERE

### Value Objects

Dataclasses frozen con validacion en construccion:

| Value Object | Validacion |
|---|---|
| `Email` | Formato de correo electronico |
| `TaxId(value)` | Cédula (10 dígitos) o RUC (13 dígitos) de Ecuador |

Los montos son `Decimal`; `round_money()` (`src/shared/domain/money.py`) redondea los totales a centavos. `TaxCode` y `TaxType` (`src/shared/domain/tax.py`) son el código de IVA y el tipo de identificación del SRI.

## Contexto de empresa

Cada empresa (tenant) es un RUC. El código sabe en qué empresa corre por un `TenantContext`
(`src/shared/domain/tenant.py`): empresa, origen (`request`, `message` o `task`), usuario y, desde S2.5,
sucursal. Es inmutable y vive en un `ContextVar`, así que lo heredan el threadpool de FastAPI (las rutas son
síncronas) y las tareas de asyncio, pero no un hilo nuevo.

Dónde se fija (siempre con `tenant_scope()` de `src/shared/infra/tenant.py`, que además agrega
`faclab.tenant.id` a los logs y al span activo):

| Origen | Quién | De dónde sale la empresa |
|---|---|---|
| Request | `AuthMiddleware` | El `tid` del access token. Un token sin `tid` responde 401 `TENANT_REQUIRED`; una ruta pública corre sin contexto |
| Mensaje de Kafka | `KafkaMessageConsumer` | El header `faclab-tenant-id` o, si no viene, el `tenant_id` del sobre. Un mensaje sin empresa se procesa sin contexto; uno con una empresa que no es UUID se descarta |
| Tarea o script | `create_sync_scope(tenant=TenantContext(...))` | La que elige la tarea, explícitamente |

Qué hace con él cada pieza:

- **Sesión de base**: `create_session_maker` registra un hook `after_begin` que, si hay contexto, ejecuta
  `set_config('app.tenant_id', <empresa>, true)` (equivale a `SET LOCAL`) al empezar cada transacción. El
  valor muere con la transacción y no pasa a otro request que reutilice la conexión. Row-Level Security lo
  usará en S2.4.
- **Repositorio base**: en un modelo con `__tenant_scoped__ = True`, `create` asigna el `tenant_id` del
  contexto y todas las lecturas (`get_by_id`, `first`, `filter*`, `count*`, `paginate*`), `update` y
  `delete` filtran por él, así que el id de otra empresa no se encuentra. Sin contexto lanza
  `TenantContextRequiredError`; una entidad que trae otra empresa, `TenantMismatchError` (los dos son errores
  de programación: 500). Las consultas que un repositorio escribe por su cuenta no están cubiertas.
- **Eventos de dominio**: `DomainEvent.tenant_id` toma la empresa del contexto al crearse.
- **Outbox**: `OutboxWriter.add` exige contexto, guarda `outbox_messages.tenant_id` y agrega el header
  `faclab-tenant-id`, que el relay envía a Kafka con el mensaje.
- **Inyección**: un handler puede recibir `TenantContext` por wireup (factory `tenant_context`, scoped).

Por ahora ningún modelo de negocio declara `__tenant_scoped__`: S2.3 agrega `tenant_id` a cada tabla y la
marca, y S2.4 activa RLS.

## Inyeccion de Dependencias

El contenedor wireup gestiona tres lifetimes:

| Lifetime | Uso | Ejemplos |
|---|---|---|
| `SINGLETON` | Una instancia compartida por toda la app | Mappers (stateless) |
| `SCOPED` | Una instancia por request HTTP | Repos, handlers, routers, sesion DB |
| `TRANSIENT` | Nueva instancia en cada resolucion | (uso puntual) |

### Registro

Cada modulo expone sus INJECTABLES en `infra/container.py`. El contenedor central en `src/container.py` los combina:

```python
# src/catalog/product/infra/container.py
INJECTABLES = [
    Injectable(obj=ProductMapper, lifetime=Lifetime.SINGLETON),
    Injectable(obj=ProductRepository, lifetime=Lifetime.SCOPED),
    Injectable(obj=CreateProductHandler, lifetime=Lifetime.SCOPED),
    ...
]

# src/container.py
def create_wireup_container():
    all_injectables = [
        *catalog_injectables,
        *inventory_injectables,
        ...
    ]
    return AsyncContainer(all_injectables)
```

### Scope por Request

Cada request HTTP obtiene un scope independiente donde todos los componentes comparten la misma sesion de base de datos, garantizando consistencia transaccional:

```
Request → wireup scope creado
    ↓
    DB Session (SCOPED) ← compartida por todos los repos del request
    Repository (SCOPED) ← resuelto con la misma session
    Handler (SCOPED)    ← resuelto con el mismo repo
    ↓
Response → scope destruido, session cerrada
```

Los event handlers se ejecutan en un **scope separado** para evitar que sus efectos secundarios afecten la transaccion principal.

## Estructura de Shared

```
src/shared/
├── domain/
│   ├── entities.py           # Entity base class
│   ├── events.py             # DomainEvent abstract base
│   ├── tenant.py             # TenantContext y su ContextVar
│   ├── value_objects.py      # Email, TaxId
│   ├── money.py              # round_money
│   ├── tax.py                # TaxCode (IVA), TaxType (identificación)
│   ├── specifications.py     # Specification[T] con operadores &, |, ~
│   └── exceptions.py         # NotFoundError, DomainError, ValidationError
├── app/
│   ├── commands.py           # Command + CommandHandler[TCmd, TResult]
│   ├── queries.py            # Query + QueryHandler[TQuery, TResult]
│   ├── repositories.py       # Repository[E] interface
│   └── events.py             # EventBus interface
└── infra/
    ├── database.py           # SQLAlchemy Base, session factory
    ├── repositories.py       # SqlAlchemyRepository[E] implementacion
    ├── mappers.py            # Mapper[E, M] base declarativo
    ├── middlewares.py        # ErrorHandlingMiddleware
    ├── tenant.py             # tenant_scope: contexto + logs + span
    ├── logging.py            # structlog configuration
    ├── telemetry_instruments.py  # OTEL histogramas y contadores
    ├── events/
    │   ├── event_bus.py          # EventBus implementacion
    │   └── decorators.py         # @event_handler decorator
    ├── kafka/
    │   ├── producer.py           # KafkaEventProducer (aiokafka); BrokerUnavailableError
    │   ├── consumer.py           # KafkaMessageConsumer: offsets tras procesar, backoff, dead letters
    │   ├── models.py             # dead_letters
    │   └── dead_letters.py       # DeadLetterStore, listar y reprocesar
    ├── outbox/
    │   ├── models.py             # outbox_messages (pending, published, failed)
    │   ├── writer.py             # OutboxWriter: guarda el mensaje en la transacción
    │   ├── relay.py              # OutboxRelay: publica lo confirmado, por empresa
    │   ├── purge.py              # purga de los publicados
    │   └── admin.py              # listar y reencolar los failed
    ├── worker/
    │   ├── runner.py             # Worker, PeriodicTask, WorkerHealth
    │   └── health.py             # healthcheck del worker
    └── adapters/
        └── telemetry.py      # OpenTelemetry instrumentation setup
```

## Flujo de Request Completo

```
HTTP POST /api/admin/sales/{id}/items
    │
    ├─ OpenTelemetryMiddleware (span del request, por fuera de todo)
    ├─ CORS Middleware
    ├─ SecurityHeadersMiddleware
    ├─ RequestIdMiddleware (X-Request-Id validado → logs, span y respuesta)
    ├─ BodySizeLimitMiddleware
    ├─ AuthMiddleware (Bearer → usuario; el resto corre en la empresa del token)
    ├─ ErrorHandlingMiddleware
    │      ├─ captura DomainError → 400
    │      ├─ captura NotFoundError → 404
    │      └─ captura ValidationError → 422
    │
    ├─ FastAPI Router → SaleRouter.add_item()
    │
    ├─ wireup scope creado (DB session compartida; cada transacción con SET LOCAL app.tenant_id)
    │
    ├─ AddSaleItemHandler.execute(AddSaleItemCommand)
    │      ├─ OTEL span iniciado
    │      ├─ metricas de invocacion
    │      ├─ SaleRepository.get_by_id(sale_id)
    │      │      └─ SaleMapper.to_entity(SaleModel)
    │      ├─ sale.add_item(item) — logica de dominio
    │      ├─ SaleRepository.update(sale)
    │      │      └─ SaleMapper.to_dict(sale) → SaleModel
    │      └─ OTEL span cerrado + metricas
    │
    └─ HTTP 200 → SaleItemOutput serializado
```

## Observabilidad

El estándar completo está en [architecture/OBSERVABILITY.md](architecture/OBSERVABILITY.md).

- **Arranque** (`main.py`): `configure_logging()`, luego `OpenTelemetry.setup()` (proveedores de
  trazas, métricas y logs), después el contenedor, que crea e instrumenta el engine de los requests, y al
  final `instrument_app()`, para que el middleware de OTel quede por fuera de los propios.
- **Recurso**: `service.name`, `service.namespace=faclab`, `service.version` (`SERVICE_VERSION`, de la
  imagen) y `deployment.environment.name`.
- **Trazas**:
  - span HTTP con convenciones estables (`http.response.status_code`, `http.route`); `/health/*` no se traza;
  - `command.*`, `query.*`, `event.publish.*` y `event.handle.*` por cada handler;
  - consultas SQL del engine de los requests;
  - `send <tópico>` (relay del outbox, hijo del contexto guardado con el mensaje) y `process <tópico>`
    (consumidor).
- **Errores**: un error de dominio (`BaseError`) es WARN y no marca el span como error; solo los
  inesperados son ERROR. `handler.errors` lleva `error.kind=domain|unexpected`.
- **Muestreo**: `ParentBased(TraceIdRatioBased)`; las consultas sin padre (polls del relay, readiness) no
  inician trazas.
- **Logs** (structlog): cada línea lleva `trace_id`, `span_id`, `http.request.id` (en HTTP) y `event.name`
  (`outbox_publish_failed` → `outbox.publish.failed`). En JSON también el servicio, la versión, el
  entorno y la traza de las excepciones. `redact_sensitive` oculta contraseñas, tokens, cookies, secretos,
  certificados, claves privadas, XML y firmas.

Variables:

```
OTEL_ENABLED=true
OTEL_OTLP_ENDPOINT=http://signoz-otel-collector:4317   # SigNoz local en faclab_network
OTEL_EXPORTER_OTLP_INSECURE=true                        # por defecto solo en local
OTEL_SERVICE_NAME=faclab-core
OTEL_SAMPLING_RATE=1.0
SERVICE_VERSION=dev                                     # la imagen lo fija en el build
```

SigNoz local: `faclab-infra/scripts/signoz.sh up` (la primera vez, crear la cuenta en
`http://localhost:8080`).
