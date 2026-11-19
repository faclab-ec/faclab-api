# Límites de solicitudes

Cada cliente de integración y cada empresa tienen un límite. Valores iniciales (se ajustarán por
plan):

| Clave | Sostenido | Ráfaga |
|---|---|---|
| Cliente | 600 por minuto | 50 |
| Empresa (todos sus clientes) | 1200 por minuto | 100 |

Cada respuesta de `/api/v1` trae el estado de la clave más cercana a su límite:

```http
RateLimit-Limit: 50
RateLimit-Remaining: 37
RateLimit-Reset: 2
RateLimit-Policy: 50;w=5
```

`RateLimit-Limit` es la ráfaga, `RateLimit-Remaining` cuántas solicitudes quedan de ella,
`RateLimit-Reset` los segundos hasta que vuelve a estar completa y `RateLimit-Policy` la ráfaga y su
ventana en segundos. Al exceder el límite:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 1
RateLimit-Remaining: 0

{"errors": [{"code": "RATE_LIMITED", "message": "Too many requests: retry in 1 seconds"}], "meta": {…}}
```

Espera `Retry-After` segundos antes de reintentar; para sincronizaciones grandes usa páginas de 200 y
`updatedSince` en vez de recorrer todo. Las rutas de comprobantes (`/api/v1/invoices`) llevan su
propia cuenta, aparte del resto. Además hay un límite por IP.
