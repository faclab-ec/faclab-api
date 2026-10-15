# ADR-0004: Persistencia de faclab-invoicing en PostgreSQL

- **Estado:** propuesto (2026-10-14)
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
  objetos.
- Los XML firmados y autorizados y el RIDE van a almacenamiento de objetos compatible con S3, con
  claves `tenants/{tenant_id}/...`.
- **Se conserva el adaptador S3**: el AWS SDK v3 funciona con cualquier proveedor compatible. El
  proveedor queda como decisión D-2.

La migración se hace en dos pasos: primero se cambia la persistencia manteniendo un solo emisor y el
mismo comportamiento (S2.7); después se vuelve multiempresa (S2.8).

## Consecuencias

- Desaparecen LocalStack y dynamodb-admin del entorno local; `faclab-infra` agrega la base de
  facturación (o la crea en el PostgreSQL del core).
- Se necesitan una herramienta de migraciones en Node (a elegir en S2.7, por ejemplo node-pg-migrate)
  y pruebas de repositorio contra PostgreSQL.
- Los secuenciales pasan a ser transaccionales y verificables con `UNIQUE (tenant_id, establishment,
  emission_point, doc_type, sequential)`.
