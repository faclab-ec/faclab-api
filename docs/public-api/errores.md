# Errores

```json
{"errors": [{"code": "INSUFFICIENT_STOCK", "message": "…", "field": "items.0.productId"}],
 "meta": {"requestId": "…", "timestamp": "…"}}
```

`code` es estable y es lo que el integrador debe mirar; `message` es para personas y puede cambiar.
`field` señala el dato de la solicitud cuando aplica. La API solo responde códigos de este catálogo:
cualquier otro caso responde el código genérico de su estado.

| Estado | Código | Significa |
|---|---|---|
| 400 | `BUSINESS_RULE_VIOLATION` | Una regla de negocio sin código propio en el catálogo |
| 400 | `BRANCH_REQUIRED` | Falta la sucursal (`X-Branch-Id` o `branchId`) |
| 400 | `INSUFFICIENT_STOCK` | El stock disponible no alcanza |
| 400 | `INSUFFICIENT_PAYMENT`, `PAYMENT_EXCEEDS_BALANCE` | Los pagos no suman el total exacto |
| 400 | `OVERRIDE_REASON_REQUIRED` | Un precio distinto al de las listas sin motivo |
| 400 | `PRODUCT_WITHOUT_PRICE` | El producto no tiene precio en ninguna lista |
| 400 | `PRESENTATION_INACTIVE` | La presentación está desactivada |
| 400 | `EMISSION_POINT_OUTSIDE_BRANCH`, `LOCATION_OUTSIDE_BRANCH` | El punto de emisión o la ubicación son de otra sucursal |
| 400 | `INVOICE_IN_PROGRESS`, `CREDIT_NOTE_REQUIRED`, `INVALID_SALE_STATUS` | La venta no se puede anular en su estado |
| 400 | `CONSTRUCTION_MATERIAL_TAX_MISMATCH` | Un material de construcción debe llevar IVA 5 % |
| 401 | `INVALID_TOKEN`, `TOKEN_EXPIRED` | Token inválido, revocado o vencido: pide otro |
| 403 | `INSUFFICIENT_SCOPE` | Al cliente le falta el scope de la ruta |
| 403 | `PERMISSION_DENIED` | No es un token de integración, o la venta es de otro cliente |
| 403 | `BRANCH_ACCESS_DENIED` | El cliente no opera en esa sucursal |
| 404 | `NOT_FOUND` | No existe, o es de otra empresa o de una sucursal que el cliente no ve |
| 409 | `CONFLICT` | Un conflicto sin código propio en el catálogo |
| 409 | `CUSTOMER_ALREADY_EXISTS` | Ya hay un cliente con esa identificación; su id va en `existingId` |
| 409 | `PRODUCT_SKU_ALREADY_EXISTS`, `PRODUCT_BARCODE_ALREADY_EXISTS`, `ALREADY_EXISTS` | Un valor único ya usado |
| 409 | `BRANCH_INACTIVE`, `EMISSION_POINT_INACTIVE`, `LOCATION_INACTIVE`, `CUSTOMER_INACTIVE` | Está desactivado |
| 409 | `RECORD_IN_USE` | Otros registros lo usan |
| 409 | `IDEMPOTENCY_IN_PROGRESS` | La solicitud con esa clave sigue en curso: reintenta |
| 409 | `WEBHOOK_ENDPOINT_LIMIT_REACHED` | La empresa ya tiene 20 endpoints de webhooks |
| 409 | `WEBHOOK_ENDPOINT_DISABLED` | El endpoint está desactivado: actívalo antes de probar o reenviar |
| 409 | `WEBHOOK_DELIVERY_PENDING` | La entrega todavía está pendiente: se enviará sola |
| 409 | `INTEGRATION_CLIENT_REVOKED` | El cliente de integración del endpoint está revocado |
| 422 | `VALIDATION_ERROR` | El cuerpo o los parámetros no son válidos (un número con decimales en vez de texto, un `sort` no permitido) |
| 422 | `REFERENCE_NOT_FOUND` | Un id del cuerpo no existe (producto, ubicación, cliente) |
| 422 | `QUANTITY_PRECISION_EXCEEDED` | Más decimales de los que admite la unidad |
| 422 | `WEBHOOK_URL_NOT_ALLOWED` | La URL del webhook no es HTTPS o resuelve a una dirección privada o local; `field: "url"` |
| 422 | `IDEMPOTENCY_KEY_REQUIRED`, `INVALID_IDEMPOTENCY_KEY`, `IDEMPOTENCY_KEY_REUSED` | Falta la clave, no es un UUID o ya se usó con otro cuerpo |
| 429 | `RATE_LIMITED` | Demasiadas solicitudes: espera `Retry-After` segundos |
| 500 | `INTERNAL_ERROR` | Error inesperado: reintenta y reporta el `requestId` si persiste |
| 503 | `PUBLIC_API_DISABLED`, `WEBHOOKS_DISABLED`, `SERVICE_UNAVAILABLE` | La API o los webhooks están apagados, o un servicio no responde |

El catálogo vive en `src/public_api/infra/errors.py` (`PUBLIC_ERROR_CODES`); un código nuevo entra
cuando un endpoint lo documenta y se anota en el [CHANGELOG](CHANGELOG.md).
