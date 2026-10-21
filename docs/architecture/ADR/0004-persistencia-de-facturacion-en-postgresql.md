# ADR-0004: Persistencia de faclab-invoicing en PostgreSQL

- **Estado:** aceptado (2026-10-20, implementado en S2.7; la parte multiempresa queda para S2.8)
- **Relacionado:** [ADR-0011](0011-despliegue-en-vps-con-docker-compose.md), [ADR-0012](0012-numeracion-de-documentos.md)

## Contexto

faclab-invoicing guarda facturas, certificados y configuración en DynamoDB y el `.p12` en S3, ambos
emulados con LocalStack. El despliegue objetivo es un VPS con Docker (decisión del usuario). Problemas
concretos encontrados:

- No hay DynamoDB fuera de AWS; LocalStack no es para producción.
- Secuencial global con una carrera que puede repetir números (G-09); se necesitan secuenciales por
  empresa, establecimiento, punto de emisión y tipo de documento.
- `GET /api/invoices` hace `Scan` completo (G-74); la vista multiempresa necesita filtros por empresa,
  estado y fecha con paginación.
- Dos reenvíos pueden crear dos facturas activas para la misma venta (G-18); se necesita una
  restricción única parcial.
- Dos esquemas de respaldo distintos (PostgreSQL y DynamoDB) en un equipo pequeño.

La persistencia ocupa unas 510 líneas detrás de interfaces de repositorio
(`src/modules/*/domain/repository.ts`), así que el cambio está acotado.

## Alternativas

| Alternativa | Ventajas | Desventajas |
|---|---|---|
| A. PostgreSQL (base propia `faclab_invoicing` en la misma instancia) | Transacciones, `UPDATE ... RETURNING` para secuenciales, índices únicos parciales, RLS, un solo respaldo | Reescribir 3 repositorios y migrar el esquema |
| B. DynamoDB real en AWS desde el VPS | Sin reescritura | Dependencia de AWS, credenciales y latencia externas, dos respaldos, consultas por empresa costosas |
| C. Compartir la base del core | Una base menos | Rompe la propiedad de los datos entre servicios |

## Decisión

**A.** Base `faclab_invoicing` con su propio usuario, en la misma instancia PostgreSQL del VPS (se puede
mover a otra instancia sin cambiar código). Tablas iniciales: `issuers` (perfil fiscal por empresa),
`certificates`, `sequences (tenant_id, establishment, emission_point, doc_type, last_value)`,
`invoices`, `invoice_events` (historial) y `dead_letters` (opcional, ver ADR-0005).

- El `.p12` se guarda cifrado (AES-256-GCM, como hoy la contraseña) en la base o en almacenamiento de
  objetos. *S2.7:* en la base.
- Los XML firmados y autorizados y el RIDE van a almacenamiento de objetos compatible con S3, con
  claves `tenants/{tenant_id}/...`.
- **Se conserva el adaptador S3**: el AWS SDK v3 funciona con cualquier proveedor compatible. El
  proveedor queda como decisión D-2. *S2.7:* el adaptador se retiró porque solo guardaba el `.p12`;
  vuelve en S4.1 para los XML y el RIDE.

La migración se hace en dos pasos: primero se cambia la persistencia manteniendo un solo emisor y el
mismo comportamiento (S2.7); después se vuelve multiempresa (S2.8).

## Consecuencias

- Desaparecen LocalStack y dynamodb-admin del entorno local; `faclab-infra` agrega la base de
  facturación (o la crea en el PostgreSQL del core).
- Se necesitan una herramienta de migraciones en Node (a elegir en S2.7, por ejemplo node-pg-migrate)
  y pruebas de repositorio contra PostgreSQL.
- Los secuenciales pasan a ser transaccionales y verificables con `UNIQUE (tenant_id, establishment,
  emission_point, doc_type, sequential)`.

## Implementación (S2.7, 2026-10-20)

- **Driver y consultas**: `pg` con SQL escrito a mano en tres repositorios
  (`src/modules/*/infra/persistence/pg-*.repository.ts`), sin ORM. Son consultas simples y así no se
  suma otra dependencia.
- **Migraciones**: node-pg-migrate con archivos `.sql` (up y down), tabla `pgmigrations` y advisory
  lock. Se corren con `npm run migrate up` como paso aparte antes de arrancar, igual que
  `make upgrade` en el core; la imagen incluye `migrations/`. La v9 se distribuye solo como ESM: el
  servicio (CommonJS) usa su CLI y solo las pruebas importan su API.
- **Tablas**:
  - `invoices`, con `version` para el bloqueo optimista y el índice único parcial
    `uq_invoices_active_sale (sale_id) WHERE status <> 'rejected'`;
  - `invoice_events`, el historial de estados, que solo crece;
  - `issuers`, todavía con una fila `default`;
  - `sequences (doc_type, last_value)`, todavía global; S2.8 le agrega empresa, establecimiento y
    punto de emisión;
  - `certificates`, con el `.p12` y su contraseña cifrados.
  - `dead_letters` llega con S3.4.
- **Secuencial**: `UPDATE sequences SET last_value = last_value + 1 ... RETURNING`, de modo que la
  primera factura es `000000001`. `invoiceSequence` de la configuración es el próximo número a emitir.
- **Entorno local**: faclab-infra tiene un PostgreSQL propio para facturación (`invoicing-db`,
  `localhost:5434`) con las bases `faclab_invoicing` y `faclab_invoicing_test`. Así, recrear la base
  del core no borra la configuración ni los certificados. En el VPS (S8.1) puede ser la misma
  instancia que la del core, cambiando solo `DATABASE_URL`.
- **Rol**: por ahora un solo rol, `faclab_invoicing`, dueño de la base. Los roles separados (dueño y
  aplicación) y RLS o filtro obligatorio por empresa llegan con S2.8.
- **Pruebas**: `test/postgres` corre contra una base `*_test`, con un esquema por archivo; en CI, con
  un servicio `postgres:17`.
