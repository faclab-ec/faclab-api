# Especificacion: Modulos Lot y Serial

Modulos de trazabilidad de inventario. **Lot** agrupa unidades por lote (fecha de fabricacion, vencimiento, cantidad). **Serial** rastrea unidades individuales con numero de serie unico y maquina de estados.

---

## 1. Lot (Lotes)

### 1.1 Entidad

| Campo             | Tipo           | Requerido | Descripcion                                    |
| ----------------- | -------------- | --------- | ---------------------------------------------- |
| `id`              | int            | auto      | PK                                             |
| `productId`       | int            | si        | FK a products, >= 1                            |
| `lotNumber`       | string(64)     | si        | Unico por producto                             |
| `manufactureDate` | date \| null   | no        | Fecha de fabricacion                           |
| `expirationDate`  | date \| null   | no        | Fecha de vencimiento                           |
| `initialQuantity` | decimal        | si        | Cantidad inicial, > 0 en creacion             |
| `currentQuantity` | decimal        | si        | Cantidad actual, >= 0                          |
| `notes`           | string \| null | no        | Max 1024 chars                                 |
| `createdAt`       | datetime       | auto      | Timestamp de creacion                          |
| `isExpired`       | bool           | computed  | `true` si `expirationDate < hoy`               |
| `daysToExpiry`    | int \| null    | computed  | Dias restantes hasta vencimiento, null si no tiene fecha |

### 1.2 Endpoints

#### `POST /api/admin/lots` — Crear lote

**Request:**
```json
{
  "productId": 1,
  "lotNumber": "LOT-2024-001",
  "initialQuantity": 100,
  "manufactureDate": "2024-01-15",
  "expirationDate": "2025-01-15",
  "notes": "Lote del proveedor A"
}
```

**Validaciones:**
- `productId`: requerido, >= 1, debe existir
- `lotNumber`: requerido, max 64 chars, unico por producto (error 400 si duplicado)
- `initialQuantity`: requerido, >= 1
- `manufactureDate`, `expirationDate`: opcionales
- `notes`: opcional, max 1024 chars

**Response (201):**
```json
{
  "data": {
    "id": 1,
    "productId": 1,
    "lotNumber": "LOT-2024-001",
    "manufactureDate": "2024-01-15",
    "expirationDate": "2025-01-15",
    "initialQuantity": 100,
    "currentQuantity": 100,
    "isExpired": false,
    "daysToExpiry": 342,
    "notes": "Lote del proveedor A",
    "createdAt": "2024-03-08T10:30:00Z"
  },
  "meta": { "requestId": "uuid", "timestamp": "ISO8601" }
}
```

> `currentQuantity` se inicializa igual a `initialQuantity`.

---

#### `PUT /api/admin/lots/{id}` — Actualizar lote

**Request (todos los campos opcionales):**
```json
{
  "currentQuantity": 95,
  "manufactureDate": "2024-01-15",
  "expirationDate": "2025-01-20",
  "notes": "Notas actualizadas"
}
```

**Validaciones:**
- `currentQuantity`: opcional, >= 0
- El lote debe existir (404 si no)

**Response:** Mismo formato que creacion con datos actualizados.

---

#### `GET /api/admin/lots` — Listar lotes

**Query params:**

| Param            | Tipo | Descripcion                                              |
| ---------------- | ---- | -------------------------------------------------------- |
| `productId`      | int  | Filtrar por producto                                     |
| `expiringInDays` | int  | Lotes que vencen en N dias (con `currentQuantity > 0`)   |
| `limit`          | int  | Paginacion                                               |
| `offset`         | int  | Paginacion                                               |

**Response:**
```json
{
  "data": [{ "...lotResponse" }],
  "meta": {
    "requestId": "uuid",
    "timestamp": "ISO8601",
    "pagination": { "total": 50, "limit": 10, "offset": 0 }
  }
}
```

> `productId` y `expiringInDays` se pueden combinar (AND).

---

#### `GET /api/admin/lots/{id}` — Obtener lote por ID

**Response:** `DataResponse[LotResponse]`. Error 404 si no existe.

---

### 1.3 Reglas de negocio

- `lotNumber` es unico por producto (constraint `uq_lot_product_lot_number`)
- `currentQuantity` nunca puede ser negativo
- Al recibir una orden de compra (`PurchaseOrderReceived`):
  - Si el lote no existe: se crea con `initialQuantity = cantidad del item`
  - Si el lote ya existe: se incrementan `initialQuantity` y `currentQuantity`
  - Se crea un `MovementLotItem` vinculando el movimiento al lote

---

## 2. Serial (Numeros de serie)

### 2.1 Entidad

| Campo             | Tipo             | Requerido | Descripcion                    |
| ----------------- | ---------------- | --------- | ------------------------------ |
| `id`              | int              | auto      | PK                             |
| `productId`       | int              | si        | FK a products, >= 1            |
| `serialNumber`    | string(128)      | si        | Unico globalmente              |
| `status`          | SerialStatus     | auto      | Default `"available"`          |
| `lotId`           | int \| null      | no        | FK a lots                      |
| `locationId`      | int \| null      | no        | FK a locations                 |
| `purchaseOrderId` | int \| null      | no        | FK a purchase_orders           |
| `saleId`          | int \| null      | no        | ID de venta asociada           |
| `notes`           | string \| null   | no        | Max 1024 chars                 |
| `createdAt`       | datetime         | auto      | Timestamp de creacion          |

### 2.2 Maquina de estados (`SerialStatus`)

```
                 ┌──────────┐
          ┌─────►│ reserved │
          │      └──────────┘
          │
     ┌────┴─────┐          ┌──────────┐
     │ available ├─────────►│   sold   ├──────►┌──────────┐
     └────┬──────┘          └──────────┘       │ returned │
          │                                     └──────────┘
          │
          │      ┌──────────┐
          └─────►│ scrapped │◄──── (desde cualquier estado)
                 └──────────┘
```

**Transiciones validas:**

| Desde       | Hacia      | Metodo           |
| ----------- | ---------- | ---------------- |
| `available` | `reserved` | `mark_reserved`  |
| `available` | `sold`     | `mark_sold`      |
| `available` | `scrapped` | `mark_scrapped`  |
| `sold`      | `returned` | `mark_returned`  |
| cualquiera  | `scrapped` | `mark_scrapped`  |

> Cualquier transicion no listada retorna error 400 (`DomainError`).

### 2.3 Endpoints

#### `POST /api/admin/serials` — Crear numero de serie

**Request:**
```json
{
  "productId": 1,
  "serialNumber": "SN-2024-001-001",
  "lotId": 5,
  "locationId": 10,
  "notes": "Recibido en PO-001"
}
```

**Validaciones:**
- `productId`: requerido, >= 1, debe existir
- `serialNumber`: requerido, max 128 chars, unico global (error 400 si duplicado)
- `lotId`, `locationId`: opcionales, >= 1, deben existir si se proporcionan
- `notes`: opcional, max 1024 chars

**Response (201):**
```json
{
  "data": {
    "id": 1,
    "productId": 1,
    "serialNumber": "SN-2024-001-001",
    "status": "available",
    "lotId": 5,
    "locationId": 10,
    "purchaseOrderId": null,
    "saleId": null,
    "notes": "Recibido en PO-001",
    "createdAt": "2024-03-08T10:30:00Z"
  },
  "meta": { "requestId": "uuid", "timestamp": "ISO8601" }
}
```

> El estado siempre se inicializa como `"available"`. `purchaseOrderId` se asigna solo via evento.

---

#### `GET /api/admin/serials` — Listar numeros de serie

**Query params:**

| Param       | Tipo   | Descripcion                                                     |
| ----------- | ------ | --------------------------------------------------------------- |
| `productId` | int    | Filtrar por producto                                            |
| `status`    | string | Filtrar por estado: `available`, `reserved`, `sold`, `returned`, `scrapped` |
| `limit`     | int    | Paginacion                                                      |
| `offset`    | int    | Paginacion                                                      |

**Response:** `PaginatedDataResponse[SerialNumberResponse]`

---

#### `GET /api/admin/serials/{id}` — Obtener por ID

**Response:** `DataResponse[SerialNumberResponse]`. Error 404 si no existe.

---

#### `PUT /api/admin/serials/{id}/status` — Cambiar estado

**Request:**
```json
{
  "status": "sold"
}
```

**Validaciones:**
- El serial debe existir (404)
- `status` debe ser un valor valido del enum
- La transicion debe ser valida segun la maquina de estados (400 si no)

**Response:** `DataResponse[SerialNumberResponse]` con estado actualizado.

---

### 2.4 Reglas de negocio

- `serialNumber` es unico globalmente (no por producto)
- El estado solo cambia via transiciones validas
- `scrapped` es estado terminal (no se puede salir de el, excepto que `mark_scrapped` se puede llamar desde cualquier estado)
- Al recibir una orden de compra (`PurchaseOrderReceived`):
  - Para items con campo `serial_numbers` (array de strings):
    - Resuelve `lotId` si el item tiene `lot_number`
    - Por cada serial: si no existe, crea con `status = available`
    - Si ya existe con mismo `productId`: skip (warning)
    - Si ya existe con diferente `productId`: skip (error log)

---

## 3. Relacion Lot <-> Serial

- Un **Lot** puede tener muchos **SerialNumbers** (via `lotId` FK)
- Un **SerialNumber** puede pertenecer a un lote o no (`lotId` nullable)
- No se puede eliminar un lote si tiene serials asociados (`ondelete=RESTRICT`)

### Flujo de recepcion de compra

```
PurchaseOrderReceived
    │
    ├──► Lot Event Handler (primero)
    │    ├── Crear/actualizar lote
    │    └── Crear MovementLotItem
    │
    └──► Serial Event Handler (despues)
         ├── Resolver lotId por (productId, lotNumber)
         └── Crear serials vinculados al lote
```

---

## 4. Formato de errores

```json
{
  "error_code": "DUPLICATE_LOT",
  "message": "Lot 'LOT-2024-001' already exists for product 1.",
  "timestamp": "2024-03-08T10:30:00Z",
  "request_id": "uuid",
  "detail": {}
}
```

| Tipo              | HTTP | Cuando                                     |
| ----------------- | ---- | ------------------------------------------ |
| `DomainError`     | 400  | Duplicados, transicion invalida, regla rota |
| `NotFoundError`   | 404  | ID no encontrado                           |
| `ValidationError` | 422  | Campos invalidos (Pydantic)                |

---

## 5. Consideraciones para frontend

### Vistas sugeridas

1. **Lista de lotes** — tabla con filtros por producto y dias para vencer, badges de color para `isExpired` y `daysToExpiry` bajo
2. **Detalle de lote** — info del lote + lista de serials asociados (`GET /serials?productId=X` + filtrar por `lotId` en frontend, o filtrar serials del lote)
3. **Lista de serials** — tabla con filtros por producto y estado, badge de color por estado
4. **Detalle de serial** — info completa + boton de cambio de estado con solo las transiciones validas habilitadas
5. **Alertas de vencimiento** — usar `GET /lots?expiringInDays=30` para dashboard

### Colores de estado serial

| Estado      | Color sugerido |
| ----------- | -------------- |
| `available` | verde          |
| `reserved`  | amarillo       |
| `sold`      | azul           |
| `returned`  | naranja        |
| `scrapped`  | rojo           |

### Naming

Todos los campos en request/response usan **camelCase**. El backend acepta tanto camelCase como snake_case en requests, pero siempre responde en camelCase.
