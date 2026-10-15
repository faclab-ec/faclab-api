# ADR-0009: Webhooks firmados con entregas desde un outbox

- **Estado:** propuesto (2026-10-14)
- **Relacionado:** [PUBLIC_API.md](../PUBLIC_API.md), [ADR-0006](0006-contratos-de-eventos-versionados.md)

## Contexto

Las integraciones necesitan enterarse de ventas, cambios de stock y facturas autorizadas sin consultar
cada pocos segundos.

## Decisión

- **Formato**:
  - Sigue la especificación Standard Webhooks, con encabezados `webhook-id`, `webhook-timestamp` y
    `webhook-signature` (`v1,<HMAC-SHA256 de "id.timestamp.cuerpo">`).
  - Cada endpoint tiene su secreto, y en la rotación conviven dos firmas.
- **Cuerpo**: `{id, type, version, occurred_at, tenant_id, data}`; `type` como `sale.confirmed`,
  `invoice.authorized`, `stock.changed`. El contrato es público y versionado, independiente de los
  eventos internos.
- **Entrega**:
  - Los eventos de dominio generan filas en `webhook_deliveries` dentro de la misma transacción (outbox
    de webhooks).
  - El `worker` las envía con timeout corto (10 s).
  - Reintenta con backoff exponencial durante hasta 3 días y desactiva el endpoint tras fallos
    sostenidos, avisando a la empresa.
- **Idempotencia y ciclos**:
  - El receptor deduplica por `webhook-id`.
  - Una escritura hecha por una integración guarda su `client_id` como origen; la suscripción puede
    excluir los eventos originados por ella misma (`exclude_own_changes`) para evitar ciclos.
- **Operación**: registro de entregas durante 30 días, reenvío manual y evento de prueba.
- **Seguridad**: solo URLs HTTPS. Se bloquean las IP privadas y locales para evitar SSRF (que el
  servidor sea usado para llamar a recursos internos).

## Consecuencias

- `stock.changed` se agrupa (por ejemplo, un evento por producto y sucursal cada 30 s) para no saturar
  a los receptores.
- El volumen de entregas entra en las métricas y dashboards (S7.1).
