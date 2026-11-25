# Cambios de la API pública

Los cambios compatibles (endpoints, campos de respuesta, campos opcionales de entrada, valores
nuevos de enums extensibles) no cambian de versión. Uno incompatible publica `/api/v2` y v1 se
mantiene al menos seis meses con `Deprecation` y `Sunset`.

## Planes — 2026-11

Sin cambios incompatibles.

- El plan de la empresa puede no incluir la API pública: entonces los tokens salen sin scopes.
- Códigos de error nuevos: `PLAN_LIMIT_REACHED` (409, con `resource` y `limit`) al crear algo que
  el plan de la empresa ya no admite, y `SUBSCRIPTION_READ_ONLY` (403) en toda escritura mientras
  la suscripción de la empresa no está activa.

## Documentación — 2026-11

Sin cambios en el contrato.

- Documentación pública en `/docs/public`: guías, la referencia de todas las rutas (también las
  de comprobantes) y los eventos de webhook en una sola página.
- Guías nuevas: **Primeros pasos** y **Facturas por webhook**.
- Ejemplos en `curl`, Python y JavaScript, que se ejecutan en cada cambio contra un sandbox.
- Portal en la aplicación: clientes de integración, secretos, uso y webhooks con sus entregas.

## v1.1.0 — 2026-11

Webhooks firmados, sin cambios incompatibles.

- `GET/POST /api/v1/webhook-endpoints`, `GET/PUT/DELETE /api/v1/webhook-endpoints/{id}`,
  `POST …/{id}/enable`, `/disable`, `/rotate-secret`, `/test`, `GET …/{id}/secret`,
  `GET …/{id}/deliveries` y `POST …/{id}/deliveries/{deliveryId}/retry` (scope `webhooks:manage`).
- Eventos v1: `sale.confirmed`, `sale.cancelled`, `invoice.authorized`, `invoice.rejected`,
  `credit_note.authorized`, `stock.changed`, `product.updated` y `webhook.test`, con su JSON Schema
  y firma Standard Webhooks.
- Códigos de error nuevos: `WEBHOOK_URL_NOT_ALLOWED`, `WEBHOOK_ENDPOINT_LIMIT_REACHED`,
  `WEBHOOK_ENDPOINT_DISABLED`, `WEBHOOK_DELIVERY_PENDING`, `INTEGRATION_CLIENT_REVOKED` y
  `WEBHOOKS_DISABLED`.

## v1.0.0 — 2026-11

Primera versión.

- `GET /api/v1/branches`; `GET/POST /api/v1/products`, `GET/PUT /api/v1/products/{id}`;
  `GET /api/v1/price-lists` y `/{id}/items`; `GET /api/v1/stock`; `GET/POST /api/v1/customers`,
  `GET/PUT /api/v1/customers/{id}`; `POST/GET /api/v1/sales`, `GET /api/v1/sales/{id}`,
  `POST /api/v1/sales/{id}/cancel`.
- Comprobantes: `GET /api/v1/invoices`, `/{id}`, `/{id}/xml`, `/{id}/ride`.
- Convenciones: dinero y cantidades como texto decimal, orden estable con `sort` y `updatedSince`,
  `Idempotency-Key` en todo POST, límites con `RateLimit-*` y catálogo público de errores.
