# Arquitectura del ecosistema Faclab

Auditoría, arquitectura objetivo y roadmap para convertir Faclab en un SaaS multiempresa y
multisucursal para ferreterías en Ecuador. Etapa 0 realizada el **2026-10-14** sobre `master` de
faclab-core, faclab-invoicing, faclab-web y faclab-infra, en modo de solo lectura (sin cambios de
código, esquema ni infraestructura).

## Documentos

| Documento | Para qué sirve |
|---|---|
| [CURRENT_STATE.md](CURRENT_STATE.md) | Qué existe hoy, verificado con código, configuración y ejecución de pruebas |
| [GAP_ANALYSIS.md](GAP_ANALYSIS.md) | Brechas con evidencia, prioridad y sesión que las resuelve; ferretería, SRI, riesgos, costos y decisiones pendientes |
| [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) | Arquitectura recomendada, propiedad de datos, consistencia, configuración, pruebas y costos |
| [MULTI_TENANCY.md](MULTI_TENANCY.md) | Modelo de empresas, sucursales, puntos de emisión y terminales; aislamiento y propagación del contexto |
| [OBSERVABILITY.md](OBSERVABILITY.md) | Estándar de logs, trazas y métricas; dashboards y alertas para SigNoz |
| [PUBLIC_API.md](PUBLIC_API.md) | API pública `/api/v1`, credenciales de integración, versionado y webhooks |
| [ROADMAP.md](ROADMAP.md) | 9 etapas y 57 sesiones con dependencias |
| [sessions/](sessions/README.md) | Una ficha por sesión con los 15 campos y un prompt listo para usar |
| [ADR/](ADR/README.md) | 12 decisiones de arquitectura con alternativas y consecuencias |

## Leyenda de evidencia

- **Verificado [V]**: demostrado leyendo el código o la configuración, o ejecutando pruebas o comandos.
- **Parcialmente verificado [P]**: hay evidencia en el código, pero falta ejecutar el escenario.
- **Pendiente de validar [PV]**: requiere infraestructura, pruebas que modifican datos o una decisión
  de negocio o legal.

Las rutas `archivo:línea` corresponden a los commits auditados y pueden cambiar. Cada sesión obliga
a verificarlas antes de editar.

## Decisiones tomadas con el usuario (2026-10-14)

- Esta documentación vive en `faclab-core/docs/architecture/`.
- Hoy solo existe desarrollo local, sin datos productivos: el esquema se puede rehacer sin migrar datos.
- El despliegue será en un VPS con Docker.
- Una empresa (tenant) equivale a un RUC.

## Resumen ejecutivo

1. **Arquitectura actual.** Es un monolito modular en Python (FastAPI, arquitectura limpia, CQRS, un
   solo PostgreSQL), más un microservicio de facturación SRI en Node y una SPA en React, unidos por
   Kafka con outbox transaccional.
   - Están bien diseñados la transacción única venta-stock-caja, el outbox con `SKIP LOCKED`, el
     consumidor idempotente, los errores con código, los permisos por ruta con prueba de guardas, y
     la DLQ y los reintentos de facturación.
2. **Lo que impide vender.**
   - No hay empresas, sucursales, puntos de emisión ni terminales.
   - Facturación tiene un solo emisor y en producción apunta al SRI de pruebas.
   - Ventas de clientes sin email nunca se facturan.
   - El secuencial puede repetirse.
   - El POS descuenta stock sin ubicación y solo admite un turno abierto en todo el sistema.
   - Las cantidades son enteras.
   - No hay nota de crédito, RIDE ni importación de datos.
   - No hay CI, imagen segura, respaldos ni monitoreo desplegado.
3. **Qué corregir primero.**
   - Fundamentos: CI, imagen y configuración, seguridad de sesión y autoría, y contrato de eventos.
   - Después, multiempresa con aislamiento en la base de datos y facturación por emisor.
   - Por último, integridad: idempotencia, inventario y mensajería que no se bloquea.
4. **Arquitectura objetivo.**
   - Mismo monolito modular más el servicio de facturación, cada uno con un `worker` aparte.
   - Facturación sobre PostgreSQL y Kafka con clave por empresa y contratos versionados.
   - Frontend con contexto de empresa, sucursal y terminal.
   - Todo desplegado con Docker Compose y Caddy en un VPS.
5. **Unificar logs, trazas y métricas.**
   - OpenTelemetry en los tres componentes con los mismos atributos de recurso.
   - Logs JSON con `trace_id` y `event.name`, y redacción de datos sensibles.
   - Collector local que reenvía a SigNoz.
   - Correcciones concretas a la instrumentación actual, que hoy no correlaciona.
6. **Dashboards y alertas.** Seis dashboards (ecosistema, API, Kafka, facturación, infraestructura y
   calidad de operaciones) y quince alertas con runbook. Los umbrales son provisionales hasta medir
   carga.
7. **API pública.** Fachada `/api/v1` sobre los comandos existentes, OAuth 2.0 *client credentials*
   con scopes y alcance por sucursal, tokens asimétricos con JWKS, `Idempotency-Key`, límites por
   cliente y webhooks firmados.
8. **Empresas y sucursales.**
   - `tenant_id` en todas las tablas con restricciones compuestas y Row-Level Security.
   - Token emitido por empresa.
   - Sucursal = establecimiento SRI, con puntos de emisión y terminales con bodega por defecto.
   - Secuenciales por establecimiento y punto de emisión en facturación.
9. **Sesiones.** 57 sesiones en 9 etapas ([ROADMAP.md](ROADMAP.md)). **La primera es S1.1, CI
   mínima en los cuatro repositorios.**
10. **Riesgos y decisiones antes de escalar.**
    - El cambio multiempresa es amplio y conviene hacerlo antes de tener datos.
    - Kafka corre con un solo nodo.
    - SigNoz consume mucha memoria.
    - Hay normativa SRI 2026 por confirmar con el contador.
    - Quedan nueve decisiones pendientes (SigNoz, almacenamiento, correo, reglas
      tributarias, planes, límites de la API, retención, documentos SRI adicionales y dominios) en [GAP_ANALYSIS.md §5.3](GAP_ANALYSIS.md#53-decisiones-pendientes).
