# Faclab Core - Sistema de Ventas e Inventarios

Sistema integral de ventas e inventarios construido con **FastAPI**, **Clean Architecture** y **CQRS**. Cubre el ciclo completo desde el catalogo de productos hasta compras, ventas y control de inventarios con trazabilidad por lotes y numeros de serie.

## Stack Tecnologico

| Componente | Tecnologia |
|---|---|
| Framework | FastAPI 0.115 |
| Lenguaje | Python 3.12 |
| Base de Datos | PostgreSQL 17 |
| ORM | SQLAlchemy 2.0 |
| Migraciones | Alembic 1.15 |
| Servidor ASGI | Uvicorn (varios workers en produccion) |
| Inyeccion de Dependencias | wireup 2.7 |
| Observabilidad | OpenTelemetry (traces, metrics, logs) |
| Logging estructurado | structlog |
| Contenedores | Docker & Docker Compose |
| Testing | pytest + pytest-cov + pytest-mock |
| Linter/Formatter | ruff |

## Modulos Implementados

| Modulo | Descripcion |
|---|---|
| **Catalogo / Productos** | SKU, nombre, descripcion, categoria, unidad de medida |
| **Catalogo / Unidades de Medida** | Registro de UoM para productos |
| **Inventario / Almacenes** | Gestion de instalaciones de almacenamiento |
| **Inventario / Ubicaciones** | Ubicaciones dentro de almacenes |
| **Inventario / Stock** | Niveles de stock en tiempo real por producto/ubicacion |
| **Inventario / Movimientos** | Entradas y salidas de inventario |
| **Inventario / Lotes** | Trazabilidad por lote (fechas de vencimiento) |
| **Inventario / Series** | Trazabilidad por numero de serie |
| **Inventario / Ajustes** | Conteos fisicos, correcciones, bajas |
| **Inventario / Transferencias** | Transferencias entre ubicaciones |
| **Inventario / Alertas** | Monitoreo de niveles minimos de stock |
| **Inventario / Reportes** | Valuacion, rotacion y resumen de inventario |
| **Clientes** | Perfiles con RUC, contactos, activacion/desactivacion |
| **Proveedores** | Perfiles con contactos y catalogo de productos |
| **Compras** | Ordenes de compra y recepciones |
| **Ventas** | Ciclo completo DRAFT → CONFIRMED → CANCELLED |
| **POS** | Punto de venta con operaciones atomicas (en desarrollo) |

## Arquitectura

El proyecto sigue **Clean Architecture** con tres capas estrictas, combinada con **CQRS** (Command Query Responsibility Segregation):

```
Domain Layer    → Entidades, Value Objects, Domain Events, Specifications
      ↓
Application     → Commands, Queries, Handlers, Repository interfaces
      ↓
Infrastructure  → Routes, SQLAlchemy Models, Mappers, Repositories, EventBus
```

### Estructura del Proyecto

```
faclab-core/
├── src/
│   ├── shared/                     # Primitivas de dominio e infraestructura compartida
│   ├── catalog/
│   │   ├── product/                # Productos y categorias
│   │   └── uom/                    # Unidades de medida
│   ├── inventory/
│   │   ├── warehouse/              # Almacenes
│   │   ├── location/               # Ubicaciones
│   │   ├── stock/                  # Niveles de stock
│   │   ├── movement/               # Movimientos IN/OUT
│   │   ├── lot/                    # Trazabilidad por lote
│   │   ├── serial/                 # Numeros de serie
│   │   ├── adjustment/             # Ajustes de inventario
│   │   ├── transfer/               # Transferencias entre ubicaciones
│   │   └── alert/                  # Alertas de stock
│   ├── customers/                  # Clientes y contactos
│   ├── suppliers/                  # Proveedores y contactos
│   ├── purchasing/                 # Ordenes de compra
│   ├── sales/                      # Ventas, items y pagos
│   ├── pos/                        # Punto de venta (en desarrollo)
│   ├── reports/                    # Reportes de inventario
│   └── container.py                # Contenedor DI central
├── config/                         # Configuracion por entorno
├── alembic/                        # Migraciones de base de datos
├── tests/                          # Tests unitarios e integracion
├── docs/                           # Documentacion adicional
├── main.py                         # Punto de entrada
└── Makefile                        # Comandos de desarrollo
```

Cada modulo de dominio sigue la misma estructura interna:

```
modulo/
├── domain/
│   ├── entities.py                 # Entidades (dataclasses con sus transiciones de estado)
│   ├── events.py                   # Eventos de dominio
│   ├── specifications.py           # Especificaciones para consultas
│   └── exceptions.py               # Excepciones de dominio
├── app/
│   ├── commands/                   # Handlers de escritura (CommandHandler)
│   └── queries/                    # Handlers de lectura (QueryHandler)
└── infra/
    ├── routes.py                   # Router classes con inyeccion wireup
    ├── validators.py               # Esquemas Pydantic
    ├── models.py                   # Modelos SQLAlchemy
    ├── mappers.py                  # Mappers declarativos Entity <-> Model
    ├── repositories.py             # Implementacion de repositorios
    └── container.py                # Registro DI del modulo
```

Ver [docs/architecture.md](docs/architecture.md) para una descripcion completa de patrones y flujos.

## API

La API expone dos superficies:

- **Admin API** (`/api/admin`) — gestion completa del back-office
- **POS API** (`/api/pos`) — operaciones del punto de venta

La documentacion interactiva (Scalar) esta disponible en:

| URL | Contenido |
|---|---|
| `http://localhost:3000/docs` | Todos los endpoints |
| `http://localhost:3000/docs/admin` | Solo endpoints Admin |
| `http://localhost:3000/docs/pos` | Solo endpoints POS |

La documentacion y los esquemas OpenAPI (`/openapi.json`, `/openapi/admin.json`, `/openapi/pos.json`) solo existen con `DOCS_ENABLED=true`, activo por defecto solo en `local`.

### Salud

Endpoints publicos, fuera de la documentacion y del log de acceso:

| URL | Respuesta |
|---|---|
| `GET /health/live` | `200 {"status": "ok"}` mientras el proceso responde |
| `GET /health/ready` | `200` con `status` `ok`, o `degraded` si Kafka esta activo pero el productor no esta conectado (el outbox conserva los mensajes); `503` con `status` `unavailable` si la base de datos no responde a `SELECT 1` |

Ver [docs/api-reference.md](docs/api-reference.md) para la referencia completa de endpoints.

## Flujo de Datos

```
HTTP Request
    → FastAPI Router
    → ErrorHandlingMiddleware
    → Router handler (wireup-injected)
    → CommandHandler / QueryHandler
        → OpenTelemetry span + metricas
        → Repository → Mapper → SQLAlchemy → PostgreSQL
        → Publicar DomainEvents (si aplica)
    → Event Handlers (en scope separado)
        → Efectos secundarios entre modulos
    → HTTP Response (JSON)
```

### Flujo de Venta

```
POST /api/admin/sales              → Crear venta (DRAFT)
POST /api/admin/sales/{id}/items   → Agregar items
POST /api/pos/sales/{id}/confirm   → Confirmar venta
    → Publica SaleConfirmed
    → Inventory crea Movement(OUT) por cada item
    → Stock se reduce automaticamente
POST /api/admin/sales/{id}/payments → Registrar pagos
POST /api/pos/sales/{id}/cancel    → Anular venta
    → Publica SaleCancelled
    → Inventory crea Movement(IN) para revertir
    → Stock se restaura
```

### Flujo de Compra

```
POST /api/admin/purchase-orders              → Crear orden de compra
POST /api/admin/purchase-order-items         → Agregar items
POST /api/admin/purchase-orders/{id}/receive → Recepcionar mercaderia
    → Publica PurchaseOrderReceived
    → Inventory crea Movement(IN) por cada item
    → Stock se incrementa automaticamente
```

## Manejo de Errores

Middleware centralizado con respuestas estructuradas:

| Tipo | HTTP Status | Uso |
|---|---|---|
| `DomainError` | 400 | Violaciones de reglas de negocio |
| `ApplicationError` | 400 | Errores de logica de aplicacion |
| `NotFoundError` | 404 | Recurso no encontrado |
| `ValidationError` | 422 | Validacion de entrada |

```json
{
  "error_code": "NOT_FOUND",
  "message": "Entity with id 1 not found",
  "timestamp": "2026-02-13T10:00:00Z",
  "request_id": "uuid",
  "detail": "contexto adicional"
}
```

## Observabilidad

- **Traces**: Cada request HTTP y ejecucion de handler genera spans automaticamente
- **Metrics**: Histogramas de duracion, contadores de invocaciones y errores
- **Logs**: structlog con formato JSON (produccion) o consola (desarrollo)
- **Exportacion**: OTLP gRPC hacia un collector configurable

## Requisitos Previos

- Docker y Docker Compose (recomendado)
- Python 3.12 para desarrollo local (la version de Docker y de CI; `ruff` y `ty` validan contra 3.11)
- PostgreSQL 17 (si se ejecuta sin Docker)

## Instalacion

```bash
git clone https://github.com/Faclab/faclab-core.git
cd faclab-core
cp .env.example .env
# Editar .env con credenciales de base de datos
```

Variables principales (la lista completa esta en `config/base.py`):

| Variable | `local` | `staging` / `production` |
|---|---|---|
| `ENVIRONMENT` | `local` (por defecto) | `staging` o `production` |
| `DATABASE_URL` | Por defecto `sqlite:///./warehouse.db` | **Obligatoria**, por ejemplo `postgresql://user:password@db:5432/faclab` |
| `CORS_ORIGINS` | Por defecto `http://localhost:3000,http://localhost:5173` | **Obligatoria**: origenes separados por comas; no admite `*` |
| `JWT_SECRET` | Por defecto un valor de desarrollo | **Obligatoria**, unica y de 32 caracteres o mas |
| `DOCS_ENABLED` | Por defecto `true` | Por defecto `false` |
| `OTEL_ENABLED`, `OTEL_OTLP_ENDPOINT` | `.env.example` apunta a SigNoz local (`http://signoz-otel-collector:4317`, levantado con `faclab-infra/scripts/signoz.sh up`) | Endpoint del collector |
| `OTEL_EXPORTER_OTLP_INSECURE` | Por defecto `true` (sin TLS) | Por defecto `false` (TLS) |
| `SERVICE_VERSION` | Por defecto `dev` | La imagen lo fija en el build: `--build-arg SERVICE_VERSION=<tag o SHA>` |

Si falta alguna variable obligatoria, el arranque falla con un mensaje que las nombra.

La imagen de produccion lee ademas `WEB_CONCURRENCY` (workers de uvicorn, por defecto 2) y `FORWARDED_ALLOW_IPS` (de quien confiar los encabezados `X-Forwarded-*`, por defecto `*` porque el API solo se expone detras del proxy).

## Ejecucion

### Docker (Recomendado)

```bash
make dev     # Servidor con hot-reload en http://localhost:3000
```

### Local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Comandos de Desarrollo

```bash
# Docker
make build                      # Construir imagenes
make start                      # Iniciar contenedores (detached)
make dev                        # Desarrollo con hot-reload
make down                       # Detener contenedores

# Base de datos
make migrations m="descripcion" # Crear migracion
make upgrade                    # Aplicar migraciones
make downgrade d=revision_id    # Revertir migracion
make seed                       # Datos de ejemplo; borra los existentes y solo corre con ENVIRONMENT=local
make seed-admin                 # Primer usuario admin desde AUTH_SEED_* (idempotente)

# Testing y calidad
make test                       # Tests con cobertura (Docker)
make test-integration           # Tests contra PostgreSQL en una BD <db>_test desechable
make lint                       # Formatear y validar codigo (ruff)
```

## Testing

```bash
# Ejecucion local
.venv/bin/python -m pytest tests/ -v
.venv/bin/python -m pytest tests/unit/ -v
.venv/bin/python -m pytest tests/integration/ -v
```

La suite incluye:
- **Tests unitarios**: Entidades, value objects, specifications, commands, queries, event handlers
- **Tests de integracion**: Flujos cross-module (Movement → Stock, Sale → Movement → Stock, PO → Movement → Stock) y guards de autorizacion sobre las rutas reales de `main.app`
- **Tests contra PostgreSQL** (`tests/integration/postgres/`): recorren la API con `TestClient` sobre una base real migrada con Alembic (rutas, specifications, reportes y flujos de inventario, POS y compras). Solo corren con `TEST_DATABASE_URL`; sin ella se saltan. `make test-integration` la arma a partir de `DATABASE_URL` y recrea la base `<db>_test` en cada corrida.

## Integracion continua

Cada PR y cada push a `master` corren `.github/workflows/ci.yml` en GitHub Actions con Python 3.12 (la version de la imagen Docker):

| Job | Que corre |
|---|---|
| `lint` | `ruff check .`, `ruff format --check .`, `ty check` |
| `test` | `pytest --cov=src` y luego `pytest tests/integration/postgres` contra un servicio `postgres:17`, con la cobertura de ambas corridas sumada |

El reporte de cobertura queda en el resumen del run y como artefacto `coverage-report` (`coverage.xml` y `htmlcov/`).

Para correr lo mismo en local:

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/ty check
.venv/bin/python -m pytest tests/ -q --cov=src
make test-integration           # las pruebas contra PostgreSQL
```

`make lint` corrige en vez de solo verificar; CI falla si queda algo sin formatear.

## Imagen de produccion

El `Dockerfile` tiene cuatro etapas:

- `builder` compila los wheels con `build-essential` y `libpq-dev`.
- `runtime` instala esos wheels sobre `python:3.12-slim` con solo `libpq5`.
- `development` agrega las dependencias de desarrollo; es la que usa `docker compose`.
- `production` copia solo `main.py`, `config/`, `src/`, `alembic/` y `alembic.ini`, y corre como el usuario sin privilegios `app` (uid 10001).

`.dockerignore` deja fuera `.env`, `.venv`, `.git`, `.data`, `tests` y `docs`.

```bash
docker build --target production -t faclab-core .
docker run --rm -p 8080:8080 \
  -e ENVIRONMENT=production -e DATABASE_URL=... -e CORS_ORIGINS=... -e JWT_SECRET=... \
  faclab-core                                  # API en :8080
docker run --rm -e ... faclab-core alembic upgrade head   # migraciones como tarea aparte
```

El contenedor valida la configuracion antes de levantar los workers: si falta una variable obligatoria, sale con codigo 1 y el mensaje en vez de reiniciar los workers en bucle. Su `HEALTHCHECK` llama a `/health/live`.

## Documentacion

| Documento | Descripcion |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Arquitectura, patrones de diseno y DI |
| [docs/api-reference.md](docs/api-reference.md) | Referencia completa de endpoints |
| [docs/modules.md](docs/modules.md) | Detalle de cada modulo de dominio |
| [docs/architecture/](docs/architecture/README.md) | Auditoria del ecosistema, arquitectura objetivo SaaS y roadmap por sesiones |

## Convenciones de Codigo

- **Formatter/Linter**: ruff (`make lint` antes de commitear)
- **Entidades de dominio**: Dataclasses que extienden `Entity`; sus métodos validan cada transición de estado y mutan la instancia (`po.send()`, `stock.reserve(n)`), y el handler la persiste con `repo.update(entity)`
- **Modelos SQLAlchemy**: Solo en la capa de infraestructura (`infra/models.py`)
- **Capas**: Domain ← Application ← Infrastructure (nunca al reves)
- **Commits**: [Conventional Commits](https://www.conventionalcommits.org/) — `feat:`, `fix:`, `refactor:`, `test:`, `docs:`
- **Cross-module**: Solo via eventos de dominio, nunca por importacion directa

## Licencia

Este proyecto esta licenciado bajo la Licencia MIT. Consulte el archivo [LICENSE](LICENSE) para mas detalles.

---

**Desarrollado por Faclab**
