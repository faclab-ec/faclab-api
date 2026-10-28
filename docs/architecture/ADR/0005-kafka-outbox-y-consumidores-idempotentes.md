# ADR-0005: Kafka con outbox transaccional y consumidores idempotentes; sin Saga

- **Estado:** aceptado (2026-10-28, S3.4; propuesto el 2026-10-14)
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

## Implementación parcial (S2.8, 2026-10-21)

- **Clave de partición**: el relay del outbox del core publica cada mensaje con su `tenant_id` como
  clave (`OutboxRelay.publish_pending` → `KafkaEventProducer.publish(key=...)`), y faclab-invoicing
  hace lo mismo en `invoices` con la empresa de la factura. Los tópicos siguen con una partición en
  local; crearlos con varias particiones por script queda para S3.4.
- **Idempotencia**: la factura activa única de facturación ya es por empresa y venta,
  `uq_invoices_active_sale (tenant_id, sale_id) WHERE status <> 'rejected'`.
- El resto (límite de intentos del outbox, `dead_letters`, purga, reproceso) sigue en S3.4.

## Implementación (S3.4, 2026-10-28)

- **Outbox**: `outbox_messages.status` (`pending`, `published`, `failed`), `next_attempt_at` y
  `OUTBOX_MAX_ATTEMPTS` (10). Un fallo espera con backoff exponencial (`OUTBOX_RETRY_BASE_SECONDS` 5,
  tope `OUTBOX_RETRY_MAX_SECONDS` 600) y frena solo a los siguientes de su empresa. Si el que falla es
  el broker (`BrokerUnavailableError`), no cuenta el intento.
- **Un relay a la vez**: cada lote toma un advisory lock de su transacción. `SKIP LOCKED` evitaba
  duplicados, pero dos relays en paralelo podían desordenar los mensajes de una empresa.
- **Retención**: los publicados se purgan a los `OUTBOX_RETENTION_DAYS` (14) desde el worker; los
  `failed` y `pending` nunca.
- **Tópicos**: `faclab-infra/scripts/create-topics.sh` crea `sales.confirmed`, `invoices` y `dlq` con
  `KAFKA_TOPIC_PARTITIONS` (6), y Kafka ya no los crea por su cuenta.
- **Consumidor del core**: backoff con `KAFKA_CONSUMER_MAX_ATTEMPTS` (5) y
  `KAFKA_CONSUMER_RETRY_BASE_SECONDS` (2, tope de un minuto). Al agotarse, el mensaje va a la tabla
  `dead_letters` (sin RLS, solo faclab_worker) y se confirma su offset. Si no se puede guardar, no se
  confirma.
- **Reproceso**: por ahora es un CLI de plataforma (`python -m src.background.cli`, `make outbox-retry`,
  `make reprocess-dead-letter`), que exige `--by` y lo registra en la fila y en el log. El endpoint de
  plataforma llega con su rol (S8.5) y la bitácora general con S3.5.
- **Resultado de la factura**: `invoices` v1 suma el campo opcional `reason` en `InvoiceRejected`. La
  venta guarda `invoice_status` (`PENDING`, `AUTHORIZED`, `REJECTED`), el id de la factura y el
  motivo, y un rechazo repetido de una factura ya rechazada no deshace un reenvío.
- **Pendiente**: el reproceso de la `dlq` de facturación y la conciliación (S4.3), y LISTEN/NOTIFY si
  el poll de 1 s del worker llega a pesar.
