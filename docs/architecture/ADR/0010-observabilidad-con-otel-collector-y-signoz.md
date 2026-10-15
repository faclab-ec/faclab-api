# ADR-0010: OpenTelemetry en cada servicio, Collector local y SigNoz

- **Estado:** propuesto (2026-10-14)
- **Relacionado:** [OBSERVABILITY.md](../OBSERVABILITY.md)

## Contexto

Core e invoicing ya exportan trazas, métricas y logs por OTLP, cada uno con convenciones propias y con
defectos de correlación (G-61 a G-67). El frontend no emite nada. SigNoz no está desplegado ni tiene
dashboards versionados.

## Decisión

1. **SDK de OpenTelemetry en cada servicio** (Python, Node y navegador) con los mismos atributos de
   recurso:
   - `service.name`, `service.version` (del build) y `deployment.environment.name`.
   - `service.namespace=faclab`.
2. **OTel Collector local en cada VPS**:
   - Recibe OTLP de los contenedores y agrega métricas del host, Docker, PostgreSQL y Kafka.
   - Filtra y redacta atributos sensibles.
   - Reenvía por OTLP con TLS a SigNoz.
   - Los servicios nunca exportan directo a SigNoz.
3. **Convenciones semánticas de OpenTelemetry** para HTTP, base de datos y mensajería. Los atributos
   propios llevan el prefijo `faclab.` (`faclab.tenant.id`, `faclab.branch.id`).
4. **Cardinalidad**: ningún id (venta, factura, usuario, empresa) como etiqueta de métrica. Las
   operaciones individuales se investigan con trazas y logs.
5. **Muestreo**:
   - `ParentBased(TraceIdRatioBased)` en los servicios, al 100 % mientras el volumen lo permita.
   - Después, muestreo en el Collector que conserve el 100 % de las trazas con error o lentas.
6. **Dashboards y alertas como código**: JSON en `faclab-infra/observability/signoz/`, importados en la
   versión de SigNoz que se despliegue.
7. **Definición de terminado**: un servicio o flujo crítico no está terminado sin logs estructurados,
   métricas esenciales y trazas de punta a punta.

## Consecuencias

- Cambiar de backend (SigNoz a otro) solo requiere reconfigurar el Collector.
- El Collector agrega un contenedor por VPS.
- La versión de SigNoz se fija al desplegar (S8.6); antes de implementar dashboards y alertas se
  verifica qué soporta esa versión.
