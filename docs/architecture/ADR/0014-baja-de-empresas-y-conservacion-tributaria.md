# ADR-0014 — Baja de empresas y conservación tributaria

- **Estado:** Aceptado (S8.7, 2026-11-25); los plazos están pendientes de confirmar con el contador y un
  abogado (D-4 y [data-protection.md](../../data-protection.md#8-dudas-abiertas-para-el-contador-y-el-abogado))
- **Sesiones:** S8.7

## Contexto

Faclab guarda datos de clientes de terceros (compradores, proveedores, usuarios). La LOPDP pide que
una empresa pueda llevarse sus datos y que, al terminar la relación, se eliminen o anonimicen; la
normativa tributaria obliga a conservar los comprobantes y los registros contables por años (7, según
las fuentes consultadas). Hasta S8.6 no había exportación por empresa, ni procedimiento de baja, ni
retención de la bitácora, y las tablas de solo inserción (`audit_log`, cierres Z, `issuer_audit`)
impiden borrar con los roles de la aplicación y del worker. Los dos servicios (core e invoicing) no
se llaman por HTTP y invoicing no conoce el estado de una empresa.

## Alternativas

1. **Borrado total tras la gracia.** Cumple «derecho al olvido» a la letra, pero destruye lo que la
   ley obliga a conservar y la contabilidad de la empresa en la base viva.
2. **Marcar la empresa como borrada y no tocar nada.** Seguro para lo tributario, pero deja datos
   personales sin necesidad para siempre.
3. **Baja por fases con anonimización** (elegida): gracia, anonimizar lo que no exige la ley, conservar
   lo que sí, eliminar todo al vencer el plazo.
4. **Orquestar la baja con un evento de Kafka entre los servicios.** Automatiza, pero exige contrato
   versionado, consumidor nuevo y reproceso de mensajes; para un procedimiento que ocurre pocas veces
   y que revisa una persona no compensa.

## Decisión

- **Exportación** (`src/data_protection/`): `export_jobs` (con RLS) y un ZIP armado por el worker en un
  hilo propio, un CSV por tabla de `Base.metadata` más `manifest.json`; ADMIN con `data:export`; una a la
  vez por empresa; permitida con la suscripción cancelada (`WRITE_ALLOWED`); el archivo vence a los 7
  días. Quedan fuera las tablas técnicas y todo secreto. Invoicing exporta una carpeta con CSV, perfil,
  XML y RIDE con su CLI (`tenant-export`), sin dependencias nuevas.
- **Baja** en tres pasos, cada uno en una transacción, auditado y con `--by`:
  1. `start`: suscripción `cancelled` (solo lectura), `grace_ends_at` (30 días) y `retention_ends_at`
     (última venta + 7 años) en `tenants`; reversible.
  2. `anonymize` (tras la gracia): borra accesos, sesiones, integraciones, webhooks, importaciones,
     mensajes y contactos; anonimiza el nombre, correo, teléfono y dirección de clientes y proveedores,
     los nombres de autor y los usuarios que no son de otra empresa; **conserva la identificación
     tributaria**. La empresa pasa a `offboarded` y no vuelve. Se detiene si quedan mensajes por
     publicar.
  3. `purge` (tras la conservación, a mano, con el RUC repetido): borra todas las filas de la empresa
     y la empresa.
- **Tablas de solo inserción:** funciones SQL `SECURITY DEFINER` de `faclab_owner`
  (`faclab_anonymize_append_only`, `faclab_purge_append_only`), restringidas a una empresa y ejecutables
  solo por `faclab_worker`; así el `REVOKE UPDATE, DELETE` sigue valiendo para todo lo demás. En
  invoicing el trigger de `issuer_audit` acepta el cambio solo dentro de la transacción que fija
  `faclab.offboarding = 'on'`.
- **Coordinación:** una CLI por servicio con el mismo RUC y un runbook con el orden. Core publica sus
  fechas; invoicing las recibe por parámetro (`--retention-ends`). No hay evento nuevo.
- **Lo firmado no se edita:** el XML autorizado y el RIDE son el registro legal; se conservan tal como
  se firmaron hasta que el plazo (Object Lock de 7 años) venza.
- **Redacción:** las claves de datos personales (`email`, `phone`, `tax_id`, `address`...) nunca van a un
  log; los errores se registran por tipo y restricción, no por el texto del controlador; el span de la
  solicitud no lleva la consulta de la URL.

## Consecuencias

- Una baja deja la contabilidad completa y sin datos personales de contacto; la identificación del
  comprador sigue en la base (y en los comprobantes) hasta el fin del plazo.
- Lo borrado persiste en los respaldos de PostgreSQL (~5 semanas) y en el bucket con Object Lock
  (hasta 7 años): la empresa debe saberlo al contratar.
- La conservación cuenta desde la última venta, más larga que desde cada comprobante: más seguro hasta
  que el contador diga otra cosa; cambiar el cómputo es cambiar una consulta.
- La purga es manual a propósito: nada borra por sí solo el registro tributario.
- Core y invoicing se mantienen sincronizados por el operador; un runbook y los `plan` de ambos lados
  son el control. Si el número de bajas crece, el evento entre servicios sería el siguiente paso.
- Pendiente: la regla del Collector (`url.query`), una anonimización por titular individual con la
  empresa activa y la purga automática de la bitácora, que se decidirá con el contador.
