# Registros de decisiones de arquitectura (ADR)

Cada ADR documenta el contexto, las alternativas, la decisión y sus consecuencias. Estados: *propuesto*,
*aceptado*, *reemplazado*. Al implementar una decisión, la sesión correspondiente cambia el estado a
*aceptado* y anota cualquier ajuste.

| ADR | Título | Estado | Sesiones |
|---|---|---|---|
| [0001](0001-monolito-modular-y-servicio-de-facturacion.md) | Monolito modular más un servicio de facturación | Propuesto | Transversal |
| [0002](0002-multiempresa-base-compartida-con-rls.md) | Multiempresa en base compartida con `tenant_id` y RLS | Propuesto | S2.2–S2.4 |
| [0003](0003-identidad-global-y-contexto-de-sucursal.md) | Identidad global, membresías y sucursal validada | Aceptado | S2.1, S2.5 |
| [0004](0004-persistencia-de-facturacion-en-postgresql.md) | Persistencia de facturación en PostgreSQL | Propuesto | S2.7, S2.8 |
| [0005](0005-kafka-outbox-y-consumidores-idempotentes.md) | Kafka con outbox y consumidores idempotentes; sin Saga | Propuesto | S3.4, S4.2, S4.3 |
| [0006](0006-contratos-de-eventos-versionados.md) | Contratos de eventos versionados | Aceptado | S1.6, S2.8 |
| [0007](0007-worker-para-procesos-en-segundo-plano.md) | Contenedor `worker` para procesos en segundo plano | Propuesto | S3.4, S4.2 |
| [0008](0008-api-publica-versionada-y-credenciales-de-integracion.md) | API pública versionada y credenciales de integración | Propuesto | S6.1–S6.3 |
| [0009](0009-webhooks-firmados.md) | Webhooks firmados | Propuesto | S6.4 |
| [0010](0010-observabilidad-con-otel-collector-y-signoz.md) | OpenTelemetry, Collector y SigNoz | Propuesto | S1.5, S7.x |
| [0011](0011-despliegue-en-vps-con-docker-compose.md) | Despliegue en VPS con Docker Compose y Caddy | Propuesto | S1.2, S8.1–S8.3 |
| [0012](0012-numeracion-de-documentos.md) | Numeración de documentos internos y tributarios | Propuesto | S2.6, S2.8, S3.3 |
