# Registro de actividades de tratamiento de datos personales (LOPDP)

> **Borrador para validar con un abogado.** Describe lo que la plataforma hace hoy; las bases
> legales, los roles y los plazos son propuestas técnicas (ver
> [data-protection.md §8](data-protection.md#8-dudas-abiertas-para-el-contador-y-el-abogado)).
> Se actualiza cada vez que se agrega una categoría de dato o un destinatario. Versión de S8.7,
> 2026-11-25.

**Responsable de los datos de las personas que operan la plataforma:** Faclab.
**Encargado de los datos que cada empresa cliente trata en la plataforma:** Faclab (por
contrato con la empresa; la empresa es la responsable).
**Contacto para ejercer derechos:** por definir con el dominio y el correo de la plataforma (D-9).

Cada fila es un tratamiento: qué se hace, con qué datos, para qué, con qué base y cuánto
tiempo, dónde vive y quién lo recibe.

## T1. Gestión de clientes y proveedores de la empresa

| | |
|---|---|
| **Titulares** | Clientes y proveedores de la empresa (personas naturales y contactos de empresas) |
| **Datos** | Nombre, tipo e identificación (cédula, RUC, pasaporte), correo, teléfono, dirección, ciudad, notas, contactos |
| **Finalidad** | Vender, comprar, cobrar, pagar y emitir comprobantes |
| **Base legal** | Ejecución del contrato entre la empresa y su cliente o proveedor; obligación tributaria (identificación en el comprobante) |
| **Dónde** | core: `customers`, `customer_contacts`, `suppliers`, `supplier_contacts`; RLS por empresa |
| **Retención** | Mientras la empresa esté activa. Al darse de baja: nombre, correo, teléfono, dirección y notas se anonimizan; la identificación tributaria se conserva hasta fin de la retención tributaria (7 años) |
| **Destinatarios** | La empresa; invoicing (identificación, nombre, correo y dirección del comprador en cada comprobante); el SRI (comprobante) |
| **Medidas** | Aislamiento por empresa con RLS, roles de base de datos separados, auditoría de cambios, exportación, anonimización |

## T2. Emisión de comprobantes electrónicos

| | |
|---|---|
| **Titulares** | Compradores |
| **Datos** | Identificación, nombre, dirección, correo y teléfono del comprador; ítems y totales |
| **Finalidad** | Emitir, firmar, enviar al SRI y entregar facturas y notas de crédito |
| **Base legal** | Obligación legal (Ley de Régimen Tributario Interno y resoluciones del SRI) |
| **Dónde** | invoicing: `invoices` (JSON de la venta), XML firmado y autorizado y RIDE en el almacenamiento de objetos, `invoice_deliveries` |
| **Retención** | **7 años** (sin confirmar). El XML y el RIDE no se editan nunca; el correo y teléfono duplicados en la base se borran al dar de baja |
| **Destinatarios** | SRI; el comprador (correo con el RIDE); proveedor SMTP |
| **Medidas** | Object Lock en modo compliance, cifrado en reposo del respaldo, aislamiento por empresa en la aplicación |

## T3. Usuarios de la plataforma

| | |
|---|---|
| **Titulares** | Usuarios (administradores, cajeros, operadores) y operadores de Faclab |
| **Datos** | Usuario, correo, nombre completo, contraseña (hash bcrypt), rol, sucursales, sesiones, intentos fallidos con IP |
| **Finalidad** | Autenticar, autorizar y proteger contra accesos indebidos |
| **Base legal** | Ejecución del contrato; interés legítimo (seguridad) |
| **Dónde** | core: `users` (identidad global), `memberships`, `user_branch_access`, `auth_sessions`, `login_failures` |
| **Retención** | Mientras haya membresía activa; sesiones 30 días tras revocarse; fallos de ingreso 15 min de ventana. Al dar de baja la empresa: membresías y sesiones se borran y los usuarios que no pertenecen a otra empresa se anonimizan |
| **Destinatarios** | Ninguno fuera de la empresa y de Faclab |
| **Medidas** | Contraseñas con hash, tokens Ed25519, bloqueo por intentos, refresco rotatorio, cookie HttpOnly |

## T4. Trazabilidad: bitácora de auditoría

| | |
|---|---|
| **Titulares** | Usuarios que hicieron la acción; titulares de lo modificado |
| **Datos** | Actor (id y nombre), acción, recurso, valores antes y después (sin contraseñas ni correos), solicitud |
| **Finalidad** | Demostrar quién hizo qué en operaciones sensibles (control interno y fiscal) |
| **Base legal** | Interés legítimo de la empresa; obligación de llevar registros |
| **Dónde** | core: `audit_log` (solo inserción para la aplicación); invoicing: `issuer_audit` |
| **Retención** | Propuesta: igual que lo tributario (7 años); sin purga automática. Al dar de baja se anonimiza el nombre del actor y se quitan nombre, usuario, correo, teléfono, dirección e identificación de los valores |
| **Destinatarios** | Administradores de la empresa |
| **Medidas** | Tabla de solo inserción, funciones SQL de dueño para la baja |

## T5. Mensajería entre servicios e integraciones

| | |
|---|---|
| **Titulares** | Los de T1 y T2 |
| **Datos** | Venta confirmada con datos del comprador (`sales.confirmed`), notas de crédito, resultados, webhooks con los datos del evento |
| **Finalidad** | Entregar lo que invoicing y las integraciones de la empresa necesitan |
| **Base legal** | Ejecución del contrato; obligación legal |
| **Dónde** | core: `outbox_messages`, `dead_letters`, `webhook_*`; Kafka; invoicing: `dead_letters` |
| **Retención** | Outbox publicado 14 días; entregas de webhooks 30 días; dead letters ya reprocesados 30 días (invoicing); en la baja se borra todo lo de la empresa |
| **Destinatarios** | invoicing; los endpoints que la empresa registre (firmados con HMAC) |
| **Medidas** | Esquema de contrato versionado, firma de webhooks, protección SSRF, tenant en cada mensaje |

## T6. Importación y exportación masiva

| | |
|---|---|
| **Titulares** | Los de T1 |
| **Datos** | Las filas del archivo que sube la empresa; el ZIP que descarga |
| **Finalidad** | Cargar datos iniciales; portabilidad y acceso |
| **Base legal** | Ejecución del contrato; derecho de acceso y portabilidad |
| **Dónde** | core: `import_job_rows` (30 días tras terminar), `export_jobs` y el ZIP en `DATA_EXPORT_DIR` (7 días) |
| **Retención** | Las indicadas |
| **Destinatarios** | El administrador que lo pide |
| **Medidas** | Solo ADMIN, una exportación a la vez por empresa, sin secretos, auditoría de la solicitud |

## T7. Perfil fiscal y certificado de la empresa

| | |
|---|---|
| **Titulares** | Titular del RUC (puede ser una persona natural) |
| **Datos** | RUC, razón social, dirección, correo, logo, certificado de firma (`.p12` y su clave, cifrados) |
| **Finalidad** | Firmar y emitir comprobantes a nombre de la empresa |
| **Base legal** | Ejecución del contrato; obligación legal |
| **Dónde** | invoicing: `issuers`, `certificates` |
| **Retención** | El perfil, 7 años (identifica al emisor de lo que se conserva). El certificado y su clave se borran al anonimizar: no hay obligación de conservar la clave privada |
| **Destinatarios** | SRI (firma) |
| **Medidas** | AES-256-GCM con clave de despliegue, nunca en logs ni exportaciones |

## T8. Telemetría y operación

| | |
|---|---|
| **Titulares** | Usuarios (identificador de usuario en eventos de seguridad) |
| **Datos** | Ids de empresa, de sucursal, de solicitud; sin cuerpos, sin correos, sin identificaciones |
| **Finalidad** | Operar y detectar fallos |
| **Base legal** | Interés legítimo |
| **Dónde** | Logs, trazas y métricas (SigNoz; hoy apagado en producción, D-1) |
| **Retención** | Logs 15 días, trazas 7, métricas 90 |
| **Destinatarios** | Equipo de Faclab |
| **Medidas** | Redacción en la aplicación y en el Collector, ver [data-protection.md §6](data-protection.md#6-datos-personales-en-logs-trazas-y-respaldos) |

## Encargados y destinatarios técnicos

| Proveedor | Para qué | Datos | Lugar |
|---|---|---|---|
| Servidor virtual (VPS) | Todo | Todos | Por definir (D-1, D-2) |
| Almacenamiento de objetos S3 | XML, RIDE, respaldos | T2, T7, respaldos | Por definir |
| Correo SMTP | Entrega del RIDE; correos de la plataforma | Correo del comprador | Por definir (D-3) |
| SRI | Autorización de comprobantes | T2 | Ecuador |

## Incidentes

Un incidente de seguridad que afecte datos personales se registra con fecha, alcance y
empresas afectadas; la notificación a la autoridad y a los titulares sigue el plazo de la
LOPDP (duda 6). El procedimiento operativo vive en los runbooks de faclab-infra.
