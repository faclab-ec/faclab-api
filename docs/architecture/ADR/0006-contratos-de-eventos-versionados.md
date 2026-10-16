# ADR-0006: Contratos de eventos versionados y pruebas de contrato

- **Estado:** aceptado (2026-10-15, implementado en S1.6)
- **Relacionado:** [ADR-0005](0005-kafka-outbox-y-consumidores-idempotentes.md), [ADR-0009](0009-webhooks-firmados.md)

## Contexto

`sales.confirmed` no tiene versión. El core envía campos nulos que facturación rechaza (G-08), y
ninguna prueba detecta esa incompatibilidad (G-76). Además, el mensaje tendrá que llevar empresa,
establecimiento y punto de emisión en la Etapa 2.

## Decisión

1. **Envelope común** para todos los mensajes entre servicios:

   ```json
   {
     "event_id": "uuid",
     "event_type": "SaleConfirmed",
     "schema_version": 1,
     "occurred_at": "2026-10-14T15:04:05Z",
     "tenant_id": "uuid",
     "aggregate_id": 123,
     "payload": { "...": "..." }
   }
   ```

   `tenant_id` se agrega en la versión que acompaña a S2.8. Los headers de Kafka llevan `traceparent`
   y `tracestate` (ya existe), y `faclab-tenant-id` para enrutar y observar sin leer el cuerpo.
2. **Fuente de verdad**: JSON Schema por evento y versión en `faclab-core/contracts/events/`
   (por ejemplo, `sales.confirmed/v1.schema.json`), junto a mensajes de ejemplo válidos y casos
   límite (cliente sin email, consumidor final).
3. **Pruebas de contrato**:
   - El core valida contra el esquema los mensajes que realmente produce.
   - Facturación valida sus esquemas zod contra los ejemplos.
   - Los dos CI usan los mismos archivos: facturación guarda una copia de `contracts/` fijada a un
     commit del core (`contracts/source.json`), la actualiza con `npm run contracts:sync -- <ref>` y
     su CI hace checkout del core en ese commit para comprobar que la copia es idéntica.
4. **Compatibilidad**:
   - Agregar campos opcionales no cambia la versión.
   - Renombrar o quitar campos, cambiar tipos u obligar un campo nuevo crea `schema_version` + 1.
   - El productor publica la versión nueva solo cuando el consumidor ya acepta ambas. El orden de
     despliegue va en cada PR.
   - Un mensaje sin `schema_version` es anterior a v1 y se lee como v1. Una versión desconocida no se
     procesa: facturación la envía a su cola de mensajes fallidos y el core la registra y la descarta.
   - Los esquemas son cerrados (`additionalProperties: false`) para que el productor no publique
     campos sin documentarlos; los consumidores ignoran los campos que no conocen.
5. **Campos nulos**: el contrato declara explícitamente qué campos aceptan `null`. Facturación no
   rechaza clientes sin email, teléfono o dirección; usa los valores que exige el SRI cuando faltan.

## Consecuencias

- Se corrige G-08 en S1.6.
- `invoices` v1 versiona el mensaje tal como existía (camelCase, sin `payload`) y agrega
  `schema_version`; adoptar el envelope completo será su v2.
- Los payloads de webhooks públicos (ADR-0009) reutilizan el mismo esquema de versionado, pero son
  contratos distintos (no se expone el evento interno tal cual).
