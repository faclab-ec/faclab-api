# ADR-0005: Kafka con outbox transaccional y consumidores idempotentes; sin Saga

- **Estado:** propuesto (2026-10-14)
- **Relacionado:** [ADR-0006](0006-contratos-de-eventos-versionados.md), [ADR-0007](0007-worker-para-procesos-en-segundo-plano.md)

## Contexto

Core y facturación ya se comunican por Kafka (`sales.confirmed`, `invoices`, `dlq`) con outbox
transaccional en el core y consumidores con confirmación manual de offset. Problemas verificados:

- El relay se detiene en el primer fallo, sin máximo de intentos (G-24).
- El consumidor del core reintenta para siempre (G-25).
- Los mensajes no llevan clave de partición.
- Kafka corre con un solo nodo y replicación 1.

## Patrones evaluados

| Patrón | Problema que resuelve aquí | ¿Se adopta? |
|---|---|---|
| Transactional Outbox | Que una venta confirmada siempre genere su mensaje, aunque Kafka esté caído | **Sí** (ya existe; se endurece) |
| Consumidor idempotente | Kafka entrega al menos una vez; un reenvío no debe duplicar facturas ni estados | **Sí** (existe; se agrega restricción única parcial en facturación) |
| Dead letter (mensajes fallidos) | Un mensaje dañado no debe bloquear la cola | **Sí**, con límite de intentos |
| Saga orquestada | Coordinar varios pasos distribuidos con compensaciones | **No**: hay un solo flujo distribuido (venta → factura) y su compensación es un documento de negocio (nota de crédito), más la conciliación |
| Inbox (tabla de mensajes recibidos) | Deduplicar cuando el handler no es idempotente por naturaleza | No por ahora: los handlers actuales son idempotentes por estado |
| Schema Registry | Validar esquemas en el broker | No: se usan JSON Schema versionados en el repositorio (ADR-0006), suficiente para dos servicios |

## Alternativas a Kafka

- **Cola en PostgreSQL** (tabla con `SKIP LOCKED`): menos infraestructura, pero obligaría a reescribir
  ambos lados y a acoplar las bases de los servicios. No se justifica.
- **Redpanda** (compatible con la API de Kafka, un binario): opción si el consumo de memoria de Kafka
  molesta en el VPS. No se adopta ahora.

## Decisión

Se conserva Kafka (KRaft, un nodo en el VPS) con estas reglas:

1. **Outbox**:
   - Máximo de intentos configurable (por ejemplo, 10). Al superarlo, el mensaje pasa a estado
     `failed` y deja de bloquear a los siguientes.
   - El orden se garantiza por clave (empresa), no globalmente.
   - Los mensajes publicados se conservan N días (por ejemplo, 14) para poder reenviarlos y luego se
     purgan.
2. **Clave de partición** = `tenant_id`; tópicos con varias particiones (por ejemplo, 6), creados por
   script y no por autocreación.
3. **Consumidores**:
   - Máximo de reintentos con backoff.
   - En el core, el mensaje que se agota va a la tabla `dead_letters`, consultable y reprocesable por
     un endpoint de plataforma; luego se confirma el offset.
   - Facturación conserva su tópico `dlq` y suma una herramienta de reproceso. Se reevalúa unificar
     después de S2.7.
4. **Idempotencia**:
   - Cada mensaje lleva `event_id`.
   - Los consumidores deduplican por estado o por restricción única, por ejemplo una factura activa
     por venta: `UNIQUE (tenant_id, sale_id) WHERE status <> 'REJECTED'`.
5. **Conciliación** periódica entre core y facturación (S4.3) como red de seguridad.

## Consecuencias

- Con un solo nodo, perder el volumen de Kafka no pierde ventas (están en PostgreSQL), pero sí mensajes
  en tránsito. Se recuperan reenviando desde el outbox o con la conciliación.
- Hay que crear los tópicos explícitamente en `faclab-infra` y en producción.
