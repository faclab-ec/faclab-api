# Protección de datos personales (S8.7)

Política técnica de Faclab como plataforma que guarda datos de terceros: qué guarda,
dónde, cuánto tiempo, cómo sale y cómo se elimina. Es la base técnica del registro de
tratamientos ([lopdp-registro-de-tratamientos.md](lopdp-registro-de-tratamientos.md)) y del
procedimiento de baja ([offboarding-runbook.md](offboarding-runbook.md)).

> **Estado legal: borrador.** Los plazos y las bases legales de este documento salen de
> fuentes secundarias y de lo que el código ya hace. Antes de la puesta en marcha los
> confirman el contador (plazos tributarios, D-4) y un abogado (LOPDP). Cada duda abierta
> está en [la sección 8](#8-dudas-abiertas-para-el-contador-y-el-abogado).

## 1. Quién es quién

- **La empresa cliente** (un tenant, un RUC) decide para qué usa los datos de sus clientes,
  proveedores y empleados. Es la responsable de ese tratamiento.
- **Faclab** los guarda y procesa por cuenta de la empresa para darle el servicio (encargado
  del tratamiento). De los datos de las personas que operan la plataforma (usuarios,
  operadores) Faclab es responsable.
- Los datos de las personas de una empresa viven en dos servicios: **faclab-core** (ventas,
  inventario, clientes, usuarios, bitácora) y **faclab-invoicing** (comprobantes
  electrónicos, perfil fiscal, certificados).

## 2. Qué datos personales hay y dónde

| Categoría | Titulares | Dónde |
|---|---|---|
| Identificación y contacto de clientes y proveedores | Clientes y proveedores de la empresa | core: `customers`, `suppliers` y sus contactos; invoicing: comprador dentro de `invoices.sale` / `credit_note`, en el XML y el RIDE de cada comprobante |
| Identidad de quienes usan la plataforma | Usuarios de la empresa, operadores de Faclab | core: `users` (identidad global), `memberships`, `auth_sessions`, `login_failures` (usuario e IP) |
| Quién hizo qué | Usuarios | core: `audit_log` (actor y valores antes/después), columnas `created_by`, `cashier_name`, `closed_by`...; invoicing: `issuer_audit` |
| Datos de envío del comprobante | Compradores | invoicing: `invoice_deliveries` (correo, respuesta del servidor) |
| Textos libres | Variable | notas de ventas, compras y proveedores; motivo de una venta estacionada |
| Mensajes entre servicios | Los anteriores | core: `outbox_messages`, `dead_letters`, `webhook_messages`; invoicing: `dead_letters` |
| Archivos subidos | Los anteriores | core: `import_job_rows` (las filas del archivo importado) |
| Perfil fiscal y certificados de la empresa | Titular del RUC (una persona natural puede ser la empresa) | invoicing: `issuers`, `certificates` (el `.p12` y su clave, cifrados) |

El RUC y la razón social de una empresa son datos de la empresa; cuando la empresa es una
persona natural lo son también de ella, y se tratan igual.

## 3. Conservación: lo que la ley obliga a guardar

El criterio de la plataforma es el mínimo: **se conserva lo que la ley tributaria y contable
obliga, durante el plazo que obliga, y todo lo demás se elimina o anonimiza al terminar la
relación.**

- **Comprobantes electrónicos y registros contables: 7 años** (configurable:
  `TAX_RETENTION_YEARS`, por defecto 7). Fuente: art. 41 del Reglamento de Comprobantes de
  Venta y art. 55 del Código Tributario, según fuentes secundarias (ver dudas). El plazo
  cuenta desde la **última venta** de la empresa (`tenants.retention_ends_at`), una
  aproximación conservadora: no desde cada comprobante.
- Qué entra en «lo que se conserva»: ventas, líneas y pagos, devoluciones, cuentas por
  cobrar y pagar, compras, inventario y movimientos con su costo, catálogo, notas de crédito,
  el XML autorizado y el RIDE, la numeración (`sequences`), el perfil fiscal, la bitácora
  (con los nombres anonimizados) y la fila de la empresa.
- Del cliente o proveedor se conserva su **identificación tributaria** (`tax_id`, tipo): es la
  que figura en el comprobante que se conserva. Su nombre, correo, teléfono y dirección se
  anonimizan en la base viva; el nombre y la dirección que el comprobante firmado ya trae
  se quedan **dentro del XML y el RIDE**, que son el registro legal y no se editan (la firma
  dejaría de valer).

## 4. Qué se elimina y cuándo

| Dato | Cuándo | Cómo |
|---|---|---|
| Archivos de exportación de la empresa | `DATA_EXPORT_RETENTION_DAYS` (7 días) después de estar listos | tarea `data_export_files_purge` |
| Filas de importaciones | `IMPORT_RETENTION_DAYS` (30) | tarea `import_rows_purge` (S5.8) |
| Claves de idempotencia | 24 h | `idempotency_keys_purge` (S3.1) |
| Mensajes publicados del outbox | 14 días | `outbox_purge` (S3.4) |
| Sesiones revocadas o vencidas | 30 días | `auth_sessions_purge` |
| Entregas de webhooks | 30 días | `webhook_deliveries_purge` |
| Mensajes muertos (dead letters) de invoicing ya reprocesados | 30 días | purga horaria del worker (S8.7); los pendientes se quedan hasta reprocesarse |
| Accesos, integraciones, webhooks, importaciones, contactos, sesiones, certificados | Al **anonimizar** una empresa dada de baja | [runbook](offboarding-runbook.md) |
| Datos personales no tributarios de lo que se conserva | Al anonimizar | ídem |
| Todo lo de la empresa | Al terminar la conservación tributaria | `purge`, a mano |

## 5. Derechos de los titulares y cómo se atienden

| Derecho | Quién lo atiende | Cómo |
|---|---|---|
| Acceso y portabilidad | La empresa, para sus clientes y trabajadores | Exportación completa `POST /api/admin/data-exports` (ZIP con un CSV por tabla) y la de invoicing (`tenant-export`: CSV, XML y RIDE) |
| Rectificación | La empresa | Edita el cliente, proveedor o usuario en la aplicación |
| Supresión / oposición de un titular **concreto** | La empresa, con Faclab | Mientras la empresa está activa, un cliente con ventas no se puede borrar (integridad contable); se anonimiza a pedido (pendiente: comando por titular) |
| Terminación del contrato | Faclab, a pedido de la empresa | Baja por fases con período de gracia |

## 6. Datos personales en logs, trazas y respaldos

### Logs y trazas
- Las claves `email`, `phone`, `tax_id`, `address`, `full_name` e `identification` nunca salen
  en un log de core (`_PII_KEYS`, `src/shared/infra/logging.py`); `mask_identification()`
  deja una cédula o RUC como `17*********01` para el log que necesite distinguir dos.
  Invoicing hace lo mismo con `customer`, `buyer`, `address`, `phone`, `taxid`.
- Los errores no vuelcan al log el texto del controlador de base de datos: una violación de
  unicidad cita la fila (`Key (tenant_id, tax_id)=(…)`). Se registra el tipo, el SQLSTATE y el
  nombre de la restricción. El motor usa `hide_parameters=True`, y `InvalidValueError`
  («Invalid email: …») se responde al cliente pero no se loguea.
- Los spans: `http.url` sin la consulta (`?q=` de las búsquedas) y excepciones sin mensaje en
  core; en invoicing `failSpan` registra el mensaje sin correos ni identificaciones.
- **Pendiente en faclab-infra** (esta sesión no toca ese repositorio): la regla
  `transform/redact` del Collector solo borra claves secretas. Añadir `url.query` y `url.full`
  a su lista y, si se quiere una segunda defensa, patrones de correo y de 10/13 dígitos
  sobre `body` y atributos de texto.
- Retención: logs 15 días, trazas 7, métricas 90 (D-7); la telemetría de producción está
  apagada hasta resolver D-1.
- Riesgo residual: el **traceback** de un error inesperado se conserva en el log para poder
  depurarlo; su mensaje puede citar un valor. Es un riesgo aceptado por el costo de operar
  a ciegas, y el log vive 15 días.

### Respaldos
- PostgreSQL (pgBackRest, cifrado AES-256): 4 respaldos completos semanales con su WAL,
  alrededor de 5 semanas de retención. **Una baja no borra de los respaldos antes de eso**: lo
  eliminado deja de estar en la base viva y desaparece de los respaldos cuando el último
  completo que lo contiene sale de la retención.
- Comprobantes (XML y RIDE) en el bucket con versionado y **Object Lock en modo compliance de
  2557 días** (7 años): ni Faclab puede borrarlos antes; un `DeleteObject` solo agrega una
  marca. Por eso la baja trata esos objetos como «conservados por ley» y el plazo del bucket
  debe confirmarse con el contador **antes** de crear el de producción (el modo compliance
  no se acorta).
- La empresa debe saber esto al contratar: el aviso de privacidad lo dice.

## 7. Cómo se comprueba

- Exportación: `tests/integration/postgres/test_data_export.py` (todas las filas de la
  empresa, ninguna de otra, sin secretos ni tablas técnicas, solo ADMIN, empresa cancelada
  puede exportar, el archivo vence) e `isolation/` (cada tenant descarga el suyo).
- Baja: `tests/integration/postgres/test_offboarding.py` (la gracia, el orden de los pasos, lo
  que se borra, lo que se conserva fila por fila, la anonimización de la bitácora y los cierres
  Z, la purga con RLS y otra empresa intacta) y `test/postgres/tenant-offboarding.test.ts` en
  invoicing.
- Logs: `tests/unit/shared/test_logging.py`, `test_middlewares.py`, `test_http_observability.py`
  e invoicing `test/shared/logger.test.ts`, `spans.test.ts`.

## 8. Dudas abiertas para el contador y el abogado

1. **Plazo de 7 años y desde cuándo cuenta.** Se usó el art. 41 del Reglamento de
   Comprobantes de Venta y el art. 55 del Código Tributario según fuentes secundarias. ¿Cuenta
   desde la emisión de cada comprobante o desde el cierre del ejercicio? Hoy se cuenta desde
   la última venta (más largo, más seguro). **Confirmar antes de crear el bucket de producción
   (Object Lock).**
2. **¿Cuáles registros más hay que conservar?** Compras, retenciones, libros contables,
   inventario valorado: se conservan todos; si la ley permite menos, se puede acortar.
3. **Consumidor final y devoluciones** (NAC-DGERCGC25-00000014): el XML anulado también se
   conserva 7 años según el art. 50.
4. **Base legal y rol de Faclab** (responsable o encargado) frente a los datos de los clientes de
   la empresa, y los contratos de encargo que la LOPDP exige.
5. **Transferencias a otro país.** El proveedor de almacenamiento (D-2) y el de correo (D-3)
   pueden quedar fuera del Ecuador.
6. **Notificación de vulneraciones** a la autoridad y a los titulares (plazos de la LOPDP) y el
   delegado de protección de datos, si la empresa o Faclab lo necesitan.
7. **Retención de la bitácora.** Propuesta: la misma que lo tributario (7 años), con los
   actores anonimizados al dar de baja. Sin purga automática por ahora.
8. **Datos de menores o categorías especiales.** Hoy ninguno: ¿la plataforma debe prohibirlo en
   sus términos?
9. **Textos libres** (notas de ventas, proveedores) pueden contener cualquier dato: se
   anonimizan en la baja y la guía de uso debe advertir no registrar datos sensibles.
