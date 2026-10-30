# ADR-0004: Persistencia de faclab-invoicing en PostgreSQL

- **Estado:** aceptado (2026-10-20, implementado en S2.7; la parte multiempresa, en S2.8 el 2026-10-21; el almacenamiento de objetos, en S4.1 el 2026-10-29)
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
  vuelve en S4.1 para los XML y el RIDE. *S4.1:* D-2 resuelta, ver abajo.

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

## Implementación multiempresa (S2.8, 2026-10-21)

- **Migración** `1792581513940_multi-company.sql`: vuelve a crear las tablas vacías (no hay datos
  productivos y la fila `default` no tenía empresa).
  - `issuers` con clave `tenant_id` y sin los campos de sucursal: el establecimiento, su dirección y
    el punto de emisión llegan con cada venta.
  - `certificates` con `tenant_id` y los RUC y cédulas que nombra el certificado (`tax_ids`).
  - `sequences (tenant_id, establishment, emission_point, doc_type, last_value)`.
  - `invoices` con `tenant_id`, `issuer_ruc`, `establishment`, `emission_point` y
    `establishment_address`; `uq_invoices_active_sale (tenant_id, sale_id)` y
    `uq_invoices_tenant_number UNIQUE (tenant_id, establishment, emission_point, sequence)`. Solo hay
    facturas (código 01), así que `doc_type` no está en la tabla.
- **Aislamiento**: filtro obligatorio de la aplicación (decisión del usuario). Los métodos de
  repositorio que usa la API reciben la empresa; el flujo (Kafka, recuperación) mueve facturas por id
  y usa la empresa de cada una. FK compuesta `(tenant_id, signing_cert_id)` hacia los certificados de
  la misma empresa. Sigue un solo rol (`faclab_invoicing`): roles separados y RLS quedan pendientes
  (ROADMAP.md).
- **Secuencial**: `INSERT ... ON CONFLICT DO UPDATE SET last_value = last_value + 1 RETURNING`, en la
  misma transacción que lo guarda en la factura; el valor inicial se fija con
  `PUT /api/sequences/{establishment}/{emissionPoint}` y no retrocede.

## Implementación del almacenamiento de objetos (S4.1, 2026-10-29)

- **D-2 (decisión del usuario):** un servicio compatible con S3 autogestionado en el VPS. El código
  solo usa la API de S3 (`S3DocumentStorage`, `@aws-sdk/client-s3`, rutas `bucket/clave` y checksums
  solo donde S3 los exige), así que el producto se cambia sin tocar código: se elige con el
  despliegue (S8.1). La copia fuera del servidor y la retención llegan con los respaldos (S8.3).
- **Local:** faclab-infra agrega `object-storage`, [Garage](https://garagehq.deuxfleurs.fr) v2.4.1 en
  un nodo, que crea su bucket (`faclab-invoicing`) y la llave de desarrollo al arrancar. Se descartó
  MinIO porque su edición comunitaria dejó de publicar imágenes en 2025 y archivó su repositorio en
  2026.
- **Qué se guarda:** el documento `autorizacion` del SRI (estado, número, fecha, ambiente y el
  comprobante firmado en CDATA) en `tenants/{tenant_id}/invoices/{año de emisión}/{clave de acceso}.xml`.
  Se sube antes de marcar la factura como autorizada: si falla, la factura sigue `sent` con el issue
  transitorio `STORAGE_UNAVAILABLE` y el reintento vuelve a consultar al SRI y a subir la misma
  clave. `invoices` guarda `authorization_number`, `authorized_at` y `authorized_xml_key`
  (migración `1793292828955_invoice-authorization`), y `GET /api/invoices/:id/authorized-xml` lo
  descarga con el filtro por empresa.
- **Configuración:** `OBJECT_STORAGE_ENDPOINT` (vacío: AWS), `OBJECT_STORAGE_REGION`,
  `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ACCESS_KEY_ID`, `OBJECT_STORAGE_SECRET_ACCESS_KEY`
  (obligatorias en producción) y `OBJECT_STORAGE_FORCE_PATH_STYLE`.
- El RIDE (S4.4) usa el mismo puerto `DocumentStorage`.

## RIDE y logo en el almacenamiento (S4.4, 2026-10-30)

- `DocumentStorage` guarda binarios (`put` con `string | Buffer`, `getBytes`, `delete`); `get` sigue
  devolviendo texto para el XML.
- **RIDE:** `tenants/{tenant_id}/invoices/{año de emisión}/{clave de acceso}.pdf`, junto a su XML. Se
  genera una vez (`RideService.ensure`) desde el XML firmado y la autorización (nunca desde el
  perfil actual) con pdfkit y bwip-js (código de barras Code 128 de la clave de acceso); no hay
  columna: si existe se responde lo guardado. La entrega de cada factura autorizada lo genera y
  `GET /api/invoices/:id/ride` genera el de las autorizadas antes de S4.4.
- **Logo del emisor:** `tenants/{tenant_id}/issuer/logo`, uno por empresa; `issuers.logo_key` y
  `logo_content_type` (migración `1793400000000_issuer-email-and-logo`). Se valida al subirlo y
  antes de dibujarlo: PNG sin entrelazado o JPEG, 300 KB y 2000 × 2000 píxeles como máximo, y el PNG
  se descomprime completo (pdfkit decodifica los PNG con transparencia en un callback, donde una
  imagen corrupta tumbaría el proceso).
- Una falla del almacenamiento en las rutas nuevas responde 503 `STORAGE_UNAVAILABLE`.

