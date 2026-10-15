# ADR-0002: Multiempresa en base compartida con `tenant_id` y Row-Level Security

- **Estado:** propuesto (2026-10-14)
- **Relacionado:** [MULTI_TENANCY.md](../MULTI_TENANCY.md), [ADR-0003](0003-identidad-global-y-contexto-de-sucursal.md)

## Contexto

No existe ningún concepto de empresa (G-01). Hay 34 tablas con restricciones únicas globales (G-06).
Los reportes y recibos consultan modelos SQLAlchemy directamente desde la capa de aplicación, así que un
filtro solo en repositorios no cubre todas las lecturas. El producto se venderá a muchas ferreterías
pequeñas y medianas, desplegado en un VPS (decisión del usuario). Hoy no hay datos productivos.

## Alternativas

| Alternativa | Aislamiento | Costo operativo | Migraciones | Reportes de plataforma |
|---|---|---|---|---|
| A. Base y esquema compartidos con `tenant_id` + RLS | Lógico, con defensa en profundidad en la base | Bajo | Una sola ejecución | Simples |
| B. Un esquema PostgreSQL por empresa | Medio | Medio (cientos de esquemas) | N ejecuciones, riesgo de desalineación | Complejos |
| C. Una base por empresa | Fuerte | Alto (conexiones, respaldos, monitoreo por base) | N ejecuciones | Muy complejos |

## Decisión

**A.** Columna `tenant_id UUID NOT NULL` en todas las tablas de negocio, con:

1. **Filtro en la aplicación**: el repositorio base asigna y filtra `tenant_id` a partir del contexto
   de la solicitud o del mensaje; nunca desde el cuerpo.
2. **Row-Level Security** de PostgreSQL en cada tabla de negocio:
   `USING (tenant_id = current_setting('app.tenant_id')::uuid)` y el mismo `WITH CHECK`. La sesión
   ejecuta `SET LOCAL app.tenant_id` al iniciar cada transacción.
3. **Roles de base de datos**:
   - `faclab_owner` es dueño de las tablas y ejecuta migraciones.
   - `faclab_app` no es dueño y no puede saltarse RLS.
   - `faclab_worker` tiene `BYPASSRLS` y se usa solo para el relay del outbox y las tareas de
     plataforma que recorren todas las empresas.
4. **Restricciones compuestas**: `UNIQUE (tenant_id, sku)`, `UNIQUE (tenant_id, tax_id)`, etc., y
   claves foráneas compuestas `(tenant_id, x_id)` en las relaciones principales para que la base
   impida mezclar empresas.
5. **Nueva línea base de migraciones**: como no hay datos productivos, se reemplaza la cadena actual
   por una migración inicial con el esquema multiempresa. La cadena vieja queda en el historial de git.

Se elige UUID para `tenants.id` porque viaja en tokens, logs y mensajes y no debe ser enumerable. Las
demás tablas conservan sus ids enteros: RLS impide usarlos para cruzar empresas.

## Consecuencias

- Las consultas de lectura que usan modelos directamente quedan protegidas por RLS sin reescribirlas.
- Hay que probar cada endpoint con datos de otra empresa (pruebas negativas en S2.4).
- Los índices pasan a empezar por `tenant_id`.
- Una empresa grande que necesite aislamiento físico podría moverse a su propia base más adelante
  (alternativa C para casos puntuales); el diseño no lo impide.
- Riesgo: olvidar `SET LOCAL` en un camino nuevo (por ejemplo, un script). Mitigación: sin `app.tenant_id`
  definido, la política no devuelve filas (falla cerrada) y hay una prueba que lo verifica.
