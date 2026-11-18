# Cambios de la API pública

Los cambios compatibles (endpoints, campos de respuesta, campos opcionales de entrada, valores
nuevos de enums extensibles) no cambian de versión. Uno incompatible publica `/api/v2` y v1 se
mantiene al menos seis meses con `Deprecation` y `Sunset` (PUBLIC_API.md §8).

## v1.1.0 — 2026-11 (S6.4)

Webhooks firmados, sin cambios incompatibles.

- `GET/POST /api/v1/webhook-endpoints`, `GET/PUT/DELETE /api/v1/webhook-endpoints/{id}`,
  `POST …/{id}/enable`, `/disable`, `/rotate-secret`, `/test`, `GET …/{id}/secret`,
  `GET …/{id}/deliveries` y `POST …/{id}/deliveries/{deliveryId}/retry` (scope `webhooks:manage`).
- Eventos v1: `sale.confirmed`, `sale.cancelled`, `invoice.authorized`, `invoice.rejected`,
  `credit_note.authorized`, `stock.changed`, `product.updated` y `webhook.test`, con su JSON Schema
  en `webhooks/v1/` y firma Standard Webhooks.
- Códigos de error nuevos: `WEBHOOK_URL_NOT_ALLOWED`, `WEBHOOK_ENDPOINT_LIMIT_REACHED`,
  `WEBHOOK_ENDPOINT_DISABLED`, `WEBHOOK_DELIVERY_PENDING`, `INTEGRATION_CLIENT_REVOKED` y
  `WEBHOOKS_DISABLED`.

## v1.0.0 — 2026-11 (S6.3)

Primera versión.

- Core: `GET /api/v1/branches`; `GET/POST /api/v1/products`, `GET/PUT /api/v1/products/{id}`;
  `GET /api/v1/price-lists` y `/{id}/items`; `GET /api/v1/stock`; `GET/POST /api/v1/customers`,
  `GET/PUT /api/v1/customers/{id}`; `POST/GET /api/v1/sales`, `GET /api/v1/sales/{id}`,
  `POST /api/v1/sales/{id}/cancel`.
- Facturación: `GET /api/v1/invoices`, `/{id}`, `/{id}/xml`, `/{id}/ride`.
- Convenciones: dinero y cantidades como texto decimal, orden estable con `sort` y `updatedSince`,
  `Idempotency-Key` en todo POST, límites con `RateLimit-*` y catálogo público de errores.
