# Cambios de la API pública

Los cambios compatibles (endpoints, campos de respuesta, campos opcionales de entrada, valores
nuevos de enums extensibles) no cambian de versión. Uno incompatible publica `/api/v2` y v1 se
mantiene al menos seis meses con `Deprecation` y `Sunset` (PUBLIC_API.md §8).

## v1.0.0 — 2026-11 (S6.3)

Primera versión.

- Core: `GET /api/v1/branches`; `GET/POST /api/v1/products`, `GET/PUT /api/v1/products/{id}`;
  `GET /api/v1/price-lists` y `/{id}/items`; `GET /api/v1/stock`; `GET/POST /api/v1/customers`,
  `GET/PUT /api/v1/customers/{id}`; `POST/GET /api/v1/sales`, `GET /api/v1/sales/{id}`,
  `POST /api/v1/sales/{id}/cancel`.
- Facturación: `GET /api/v1/invoices`, `/{id}`, `/{id}/xml`, `/{id}/ride`.
- Convenciones: dinero y cantidades como texto decimal, orden estable con `sort` y `updatedSince`,
  `Idempotency-Key` en todo POST, límites con `RateLimit-*` y catálogo público de errores.
