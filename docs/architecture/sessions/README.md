# Sesiones de implementación

Cada archivo contiene los 15 campos obligatorios y un prompt autocontenido para ejecutar la sesión en una conversación nueva de Claude Code. Orden y dependencias en [ROADMAP.md](../ROADMAP.md).


## Etapa 1 — Fundamentos

- [S1.1 — CI mínima en los cuatro repositorios](S1.1-ci-minima.md) · depende de: —
- [S1.2 — Operación del core: imagen, salud y configuración por entorno](S1.2-operacion-del-core.md) · depende de: S1.1
- [S1.3 — Empaquetado y configuración por entorno de invoicing y web](S1.3-empaquetado-invoicing-y-web.md) · depende de: S1.1
- [S1.4 — Endurecimiento de seguridad del API y la sesión](S1.4-seguridad-del-api.md) · depende de: S1.2
- [S1.5 — Estándar de observabilidad base](S1.5-observabilidad-base.md) · depende de: S1.2, S1.3
- [S1.6 — Contrato de eventos v1 y pruebas de contrato](S1.6-contrato-de-eventos-v1.md) · depende de: S1.1

## Etapa 2 — Multiempresa y multisucursal

- [S2.1 — Plataforma: empresas, membresías y token por empresa](S2.1-tenants-y-membresias.md) · depende de: S1.4
- [S2.2 — Contexto de empresa en requests, mensajes y tareas](S2.2-contexto-de-tenant.md) · depende de: S2.1
- [S2.3 — `tenant_id` en todos los módulos y nueva línea base de migraciones](S2.3-tenant-id-en-modulos.md) · depende de: S2.2
- [S2.4 — Row-Level Security y pruebas negativas de aislamiento](S2.4-rls-y-aislamiento.md) · depende de: S2.3
- [S2.5 — Sucursales, establecimientos, puntos de emisión, terminales y acceso por sucursal](S2.5-sucursales-y-puntos-de-emision.md) · depende de: S2.3
- [S2.6 — POS por terminal: turnos, cajero, ubicación de stock y numeración](S2.6-pos-por-terminal.md) · depende de: S2.5
- [S2.7 — Persistencia de faclab-invoicing en PostgreSQL](S2.7-invoicing-en-postgresql.md) · depende de: S1.3, S1.6
- [S2.8 — Facturación multiempresa por establecimiento y punto de emisión](S2.8-facturacion-multiempresa.md) · depende de: S2.6, S2.7
- [S2.9 — Frontend multiempresa y multisucursal](S2.9-frontend-multiempresa.md) · depende de: S2.5, S2.6, S2.8

## Etapa 3 — Integridad transaccional

- [S3.1 — Idempotencia de comandos con `Idempotency-Key`](S3.1-idempotencia.md) · depende de: S2.6
- [S3.2 — Reglas de inventario: sin negativos, disponibilidad real y ajustes correctos](S3.2-reglas-de-inventario.md) · depende de: S2.6
- [S3.3 — Ventas, pagos, anulaciones y precisión monetaria](S3.3-ventas-pagos-y-precision.md) · depende de: S2.6
- [S3.4 — Worker separado y mensajería que no se bloquea](S3.4-worker-y-mensajeria-resiliente.md) · depende de: S2.3
- [S3.5 — Bitácora de auditoría de operaciones sensibles](S3.5-bitacora-de-auditoria.md) · depende de: S2.3, S1.4

## Etapa 4 — Facturación robusta

- [S4.1 — Cumplimiento de la factura electrónica](S4.1-cumplimiento-de-la-factura.md) · depende de: S2.8
- [S4.2 — Procesamiento del SRI desacoplado del consumidor](S4.2-sri-desacoplado.md) · depende de: S2.7
- [S4.3 — Conciliación entre ventas y comprobantes, y reproceso de fallidos](S4.3-conciliacion-y-reproceso.md) · depende de: S3.4, S4.2
- [S4.4 — RIDE y envío del comprobante al cliente](S4.4-ride-y-correo.md) · depende de: S4.1
- [S4.5 — Nota de crédito electrónica](S4.5-nota-de-credito.md) · depende de: S4.1, S4.2, S3.3

## Etapa 5 — Operación de ferretería

- [S5.1 — Cantidades decimales en todo el flujo](S5.1-cantidades-decimales.md) · depende de: S3.3
- [S5.2 — Unidades de medida, presentaciones y conversiones](S5.2-unidades-y-presentaciones.md) · depende de: S5.1
- [S5.3 — Listas de precios](S5.3-listas-de-precios.md) · depende de: S5.2
- [S5.4 — Cotizaciones con vigencia y conversión a venta](S5.4-cotizaciones.md) · depende de: S5.3
- [S5.5 — Ventas a crédito y cuentas por cobrar](S5.5-credito-y-cuentas-por-cobrar.md) · depende de: S5.3, S3.3
- [S5.6 — Costo promedio ponderado y kárdex valorizado](S5.6-costo-promedio-y-kardex.md) · depende de: S5.1, S3.2
- [S5.7 — Compras: IVA, devoluciones a proveedor y cuentas por pagar básicas](S5.7-compras-devoluciones-e-iva.md) · depende de: S5.6
- [S5.8 — Importación masiva de datos iniciales](S5.8-importacion-masiva.md) · depende de: S5.2, S5.3
- [S5.9 — Cierre de caja formal](S5.9-cierre-de-caja.md) · depende de: S2.6, S3.5

## Etapa 6 — API pública

- [S6.1 — Firma asimétrica de tokens y JWKS](S6.1-jwt-asimetrico-y-jwks.md) · depende de: S2.1
- [S6.2 — Credenciales de integración con OAuth 2.0 *client credentials*](S6.2-credenciales-de-integracion.md) · depende de: S6.1, S2.5, S3.5
- [S6.3 — API pública `/api/v1` y límites de solicitudes](S6.3-api-v1.md) · depende de: S6.2, S3.1
- [S6.4 — Webhooks firmados](S6.4-webhooks.md) · depende de: S6.2, S3.4
- [S6.5 — Portal de integraciones, documentación y sandbox](S6.5-portal-documentacion-y-sandbox.md) · depende de: S6.3, S6.4

## Etapa 7 — Observabilidad completa

- [S7.1 — Métricas técnicas y de negocio del core](S7.1-metricas-del-core.md) · depende de: S1.5, S3.4
- [S7.2 — Métricas y trazas de facturación](S7.2-metricas-de-facturacion.md) · depende de: S1.5, S4.2
- [S7.3 — Observabilidad del frontend](S7.3-observabilidad-del-frontend.md) · depende de: S1.5
- [S7.4 — OTel Collector e infraestructura](S7.4-collector-e-infraestructura.md) · depende de: S1.5
- [S7.5 — Dashboards y alertas como código](S7.5-dashboards-y-alertas.md) · depende de: S7.1, S7.2, S7.3, S7.4
- [S7.6 — Observabilidad en pruebas y definición de terminado](S7.6-observabilidad-en-pruebas.md) · depende de: S7.1, S7.2

## Etapa 8 — SaaS y producción

- [S8.1 — Stack de producción en el VPS](S8.1-stack-de-produccion-en-vps.md) · depende de: S1.2, S1.3, S2.7, S3.4
- [S8.2 — Entrega continua y versionado coordinado](S8.2-entrega-continua.md) · depende de: S8.1, S1.1
- [S8.3 — Respaldos y recuperación](S8.3-respaldos-y-recuperacion.md) · depende de: S8.1
- [S8.4 — Planes, suscripciones y límites de uso](S8.4-planes-y-limites.md) · depende de: S2.5
- [S8.5 — Onboarding de empresas y consola de plataforma](S8.5-onboarding-y-consola.md) · depende de: S8.4, S2.8, S5.8
- [S8.6 — SigNoz en operación](S8.6-signoz-en-operacion.md) · depende de: S7.5, S8.1
- [S8.7 — Protección de datos personales](S8.7-proteccion-de-datos.md) · depende de: S8.3

## Etapa 9 — Piloto y endurecimiento

- [S9.1 — Pruebas E2E del flujo completo](S9.1-e2e-flujo-completo.md) · depende de: S4.5, S8.1
- [S9.2 — Pruebas de carga y línea base de umbrales](S9.2-carga-y-linea-base.md) · depende de: S8.1, S7.5
- [S9.3 — Revisión de seguridad y aislamiento](S9.3-revision-de-seguridad.md) · depende de: S6.3, S8.1
- [S9.4 — Puesta en marcha del piloto](S9.4-puesta-en-marcha-del-piloto.md) · depende de: S9.1, S9.2, S9.3, S8.3, S8.5
- [S9.5 — Cierre del piloto y siguiente backlog](S9.5-cierre-del-piloto.md) · depende de: S9.4
