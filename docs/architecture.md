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

Los mensajes hacia otros servicios no se publican desde el handler: `OutboxWriter.add()` los guarda en la tabla `outbox_messages` dentro de la misma transacción del request, junto con el contexto de traza. Si la transacción se revierte, el mensaje desaparece con ella. `OutboxRelay` (un hilo que arranca el lifespan cuando `KAFKA_ENABLED`) publica los mensajes confirmados en orden, usando `FOR UPDATE SKIP LOCKED` para que varias réplicas no dupliquen envíos; se despierta tras cada commit que escribió uno y reintenta los fallos en la siguiente vuelta (`OUTBOX_POLL_INTERVAL_SECONDS`).

Hoy el único mensaje es `sales.confirmed` para faclab-invoicing; lo arma `src/invoicing/infra/event_handlers.py` con los datos del cliente y los productos. Cada ítem lleva además `invoice_discount`, `invoice_base` e `invoice_tax`: sus montos en la factura del SRI, redondeados a centavos y con el descuento global ya prorrateado (`invoice_lines` en `src/sales/domain/services.py`). Las bases suman `subtotal - descuento` y bases más IVA suman el total cobrado, así que faclab-invoicing los copia al XML sin recalcular nada.

### Consumidor de Kafka

`KafkaMessageConsumer` (`src/shared/infra/kafka/consumer.py`) también corre en un hilo que arranca el lifespan cuando `KAFKA_ENABLED`, con el consumer group `KAFKA_CONSUMER_GROUP_ID` (por defecto `faclab-core`). Entrega cada mensaje al handler de su topic y confirma el offset solo si el handler termina bien; si falla, vuelve a ese offset y lo reintenta, así que los handlers deben ser idempotentes. Un mensaje que no es JSON se descarta. Si Kafka no está disponible, el consumidor y el productor reintentan la conexión en vez de morir.

Hoy lee el topic `invoices`, donde faclab-invoicing publica cada transición de sus facturas (created → signed → sent → authorized / rejected). `src/invoicing/infra/invoice_messages.py` solo actúa ante `InvoiceAuthorized`: la venta pasa de `CONFIRMED` a `INVOICED` y se publica `SaleInvoiced`. Si la venta ya estaba facturada no hace nada; si no existe o ya no está confirmada (p. ej. se anuló antes de que el SRI respondiera), lo registra como error y sigue, porque eso se resuelve con una nota de crédito y no reintentando.

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
    ├── logging.py            # structlog configuration
    ├── telemetry_instruments.py  # OTEL histogramas y contadores
    ├── events/
    │   ├── event_bus.py          # EventBus implementacion
    │   └── decorators.py         # @event_handler decorator
    ├── kafka/
    │   ├── producer.py           # KafkaEventProducer (aiokafka)
    │   └── consumer.py           # KafkaMessageConsumer: offsets tras procesar, reintentos
    ├── outbox/
    │   ├── models.py             # outbox_messages
    │   ├── writer.py             # OutboxWriter: guarda el mensaje en la transacción
    │   └── relay.py              # OutboxRelay: publica lo confirmado
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
    ├─ ErrorHandlingMiddleware
    │      ├─ captura DomainError → 400
    │      ├─ captura NotFoundError → 404
    │      └─ captura ValidationError → 422
    │
    ├─ FastAPI Router → SaleRouter.add_item()
    │
    ├─ wireup scope creado (DB session compartida)
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
