# Baja de una empresa y exportación de sus datos (S8.7)

Procedimiento del operador de Faclab. Cuándo se usa: la empresa terminó su contrato (o lo pide
por escrito) y hay que entregarle sus datos, dejarla en solo lectura, y después eliminar lo que la
ley no obliga a guardar. **Todo es en dos servicios** (core e invoicing) y se hace con el mismo RUC,
en este orden. Política y plazos: [data-protection.md](data-protection.md).

> Los pasos destructivos (`anonymize`, `purge`) no se ofrecen por HTTP, escriben solo con
> `--execute`, y sin él muestran un plan. Hay un plan `--dry-run` por defecto: **léalo antes**.

## 0. Antes de empezar

- La solicitud de la empresa, por escrito, de quien puede pedirla (administrador del RUC).
- Que `outbox-failed` y `dead-letters` de core, y `dead-letters` de invoicing, no tengan nada
  pendiente de esa empresa: la anonimización se detiene si quedan mensajes por publicar o
  comprobantes sin resultado.
- Quién ejecuta (`--by`), para el log y la bitácora.

## 1. Entregar sus datos

**Core.** Dos caminos:

- El administrador de la empresa la pide en la aplicación (`POST /api/admin/data-exports`,
  permiso `data:export`, solo ADMIN; funciona aun con la suscripción cancelada) y la descarga en
  `GET /api/admin/data-exports/{id}/download`. El worker la arma (tarea `data_exports`) y la
  borra a los 7 días.
- El operador, sin pasar por la aplicación:
  `make offboard-tenant args="export --ruc 1790012345001 --by ana"`. Escribe el ZIP en
  `DATA_EXPORT_DIR/<id de la empresa>/` y muestra su ruta; hay que sacarlo del volumen y
  entregarlo (se borra a los 7 días).

El ZIP trae un CSV por tabla de la empresa y `manifest.json` (tablas, filas, qué se dejó fuera).

**Invoicing.**

```bash
npm run build
npm run cli -- tenant-export --ruc 1790012345001 --out /srv/exports --by ana
cd /srv/exports && zip -r faclab-invoicing-1790012345001.zip faclab-invoicing-1790012345001
```

La carpeta trae `invoices.csv` (con el comprador), `invoice-deliveries.csv`, `certificates.csv`
(solo metadatos, nunca el `.p12`), `sequences.csv`, `issuer-audit.csv`, `issuer.json`, `xml/` y
`ride/` (los RIDE que faltaban se generan al exportar) y `manifest.json`. Verifique que
`failed` esté vacío.

Entregue ambos archivos por un canal seguro y registre la fecha.

## 2. Iniciar la baja

```bash
# core: cancela la suscripción (solo lectura) y fija la gracia y el fin de la conservación
make offboard-tenant args="start --ruc 1790012345001 --by ana"
# o, desde la consola: POST /api/platform/tenants/{id}/offboarding
# invoicing, con la misma fecha de fin de conservación que mostró core
npm run cli -- tenant-offboard-start --ruc 1790012345001 --by ana --retention-ends 2033-11-25
```

- Período de gracia: `OFFBOARDING_GRACE_DAYS` (30). La empresa entra, consulta y exporta;
  no puede crear ni cambiar nada.
- Fin de la conservación: la **última venta** + `TAX_RETENTION_YEARS` (7).
- Para volver atrás (solo antes de anonimizar): `make offboard-tenant args="cancel --ruc … --by …"`
  o `DELETE /api/platform/tenants/{id}/offboarding`, y `tenant-offboard-cancel` en invoicing.

## 3. Anonimizar (después de la gracia)

```bash
make offboard-tenant args="plan --ruc 1790012345001 --by ana"       # qué haría y qué se queda
make offboard-tenant args="anonymize --ruc 1790012345001 --by ana --execute"
npm run cli -- tenant-offboard-plan --ruc 1790012345001
npm run cli -- tenant-anonymize --ruc 1790012345001 --by ana --execute
```

Core borra accesos, sesiones, integraciones, webhooks, importaciones, exportaciones,
mensajes, contactos y membresías; anonimiza nombre, correo, teléfono y dirección de clientes y
proveedores (la identificación se queda), los nombres de quien hizo cada venta, turno o compra,
la bitácora y los cierres Z, y los usuarios que no pertenecen a otra empresa. Invoicing borra
certificados (la clave privada), mensajes muertos y el logo, y limpia correo y teléfono del
comprador y las respuestas del servidor de correo fuera de los comprobantes. El XML y el RIDE
**no se tocan**. Con `OFFBOARDING_AUTO_ANONYMIZE=true` el worker de core lo hace solo al vencer la
gracia (por defecto no).

Después: nadie de la empresa puede iniciar sesión (un token ya emitido dura hasta 15 minutos).
`--skip-grace` existe para una empresa de prueba.

## 4. Eliminar (después de la conservación)

Solo cuando `retentionEndsAt` pasó y el contador lo confirmó.

```bash
make offboard-tenant args="purge --ruc 1790012345001 --by ana --confirm-ruc 1790012345001 --execute"
npm run cli -- tenant-purge --ruc 1790012345001 --by ana --confirm-ruc 1790012345001 --execute
```

Core borra todas las filas de la empresa y, al final, la empresa. No se puede deshacer. Su bitácora
se va con ella: solo queda la línea `tenant_purged` en los logs. Invoicing borra sus filas y los
objetos de `tenants/<id>/`, y conserva en `tenant_offboarding` el comprobante de que se eliminó
(fecha y quién).

**Respaldos.** Lo borrado sigue en los respaldos de PostgreSQL hasta unas 5 semanas y los XML y
RIDE en el bucket con Object Lock hasta los 7 años: es lo que dice la política y lo que se le dice a
la empresa.

## 5. Verificación

1. `plan` de ambos servicios sin filas por purgar ni por anonimizar (solo `retain` hasta la
   eliminación).
2. `GET /api/platform/tenants/{id}`: estado `offboarded`, fechas puestas.
3. En core: `SELECT count(*) FROM customers WHERE tenant_id = '…' AND email IS NOT NULL` es 0.
4. Después del paso 4, ninguna tabla tiene filas del `tenant_id`.

## 6. Si algo falla

- Cada paso corre en una transacción: un error no deja la baja a medias. Repita el comando.
- `OFFBOARDING_PENDING_MESSAGES` / `OFFBOARDING_PENDING_DOCUMENTS`: espere a que salgan o
  reprocese lo pendiente.
- `TENANT_OFFBOARDED`: ya se anonimizó; no se puede reactivar ni cancelar.
- Se pidió por error después de anonimizar: se restaura desde el respaldo de PostgreSQL más
  reciente anterior a la anonimización (ver `faclab-infra/deploy/production/RESPALDOS.md`), en la
  ventana de ~5 semanas.
