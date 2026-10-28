# Especificación del Módulo de Compras (Purchasing)

## Descripción General

El módulo de compras gestiona el ciclo de vida completo de las órdenes de compra a proveedores: desde la creación del borrador, el envío al proveedor, la recepción parcial o total de mercancía, hasta la cancelación. Al recibir mercancía, el sistema genera automáticamente movimientos de inventario (IN), actualiza stock, crea lotes y registra números de serie cuando aplique.

---

## Enums

### PurchaseOrderStatus

| Valor       | Descripción                                      |
| ----------- | ------------------------------------------------ |
| `draft`     | Borrador, permite edición de ítems y datos        |
| `sent`      | Enviada al proveedor, no se puede editar          |
| `partial`   | Recepción parcial de mercancía                    |
| `received`  | Toda la mercancía ha sido recibida                |
| `cancelled` | Orden cancelada                                   |

---

## Máquina de Estados

```
              send()           receive (parcial)
  DRAFT ──────────► SENT ─────────────────────► PARTIAL
    │                 │                            │
    │                 │     receive (completo)      │  receive (completo)
    │                 └──────────────────► RECEIVED ◄┘
    │                 │
    │    cancel()     │   cancel()
    └──► CANCELLED ◄──┘
              ▲
              │  cancel()
         PARTIAL ─┘
```

**Reglas de transición:**

| Desde      | Hacia       | Acción                                        |
| ---------- | ----------- | --------------------------------------------- |
| `draft`    | `sent`      | `POST /{id}/send`                             |
| `draft`    | `cancelled` | `POST /{id}/cancel`                           |
| `sent`     | `partial`   | `POST /{id}/receive` (recepción incompleta)   |
| `sent`     | `received`  | `POST /{id}/receive` (recepción completa)     |
| `sent`     | `cancelled` | `POST /{id}/cancel`                           |
| `partial`  | `received`  | `POST /{id}/receive` (se completa el faltante)|
| `partial`  | `cancelled` | `POST /{id}/cancel`                           |
| `received` | —           | Estado final, no permite más transiciones      |
| `cancelled`| —           | Estado final, no permite más transiciones      |

---

## Entidades

### PurchaseOrder

| Campo          | Tipo              | Requerido | Default     | Descripción                              |
| -------------- | ----------------- | --------- | ----------- | ---------------------------------------- |
| `id`           | `int`             | auto      | —           | ID único                                 |
| `supplierId`   | `int`             | sí        | —           | ID del proveedor                         |
| `orderNumber`  | `string`          | auto      | —           | Código único generado (`PO-{año}-{seq}`) |
| `status`       | `PurchaseOrderStatus` | auto  | `draft`     | Estado actual de la orden                |
| `subtotal`     | `number`          | auto      | `0`         | Suma de costos de todos los ítems, redondeada a centavos |
| `tax`          | `number`          | auto      | `0`         | Impuestos (actualmente siempre 0)        |
| `total`        | `number`          | auto      | `0`         | subtotal + tax                           |
| `notes`        | `string \| null`  | no        | `null`      | Notas opcionales                         |
| `expectedDate` | `datetime \| null`| no        | `null`      | Fecha esperada de entrega                |
| `createdAt`    | `datetime \| null`| auto      | —           | Fecha de creación                        |
| `updatedAt`    | `datetime \| null`| auto      | —           | Fecha de última actualización            |

> **Nota:** `orderNumber` se genera automáticamente con formato `PO-{año}-{secuencial:04d}`. Ejemplo: `PO-2026-0001`. Desde S3.3 el secuencial sale del contador de la empresa en `document_sequences` (ADR-0012), que se bloquea hasta que la orden se guarda: dos órdenes creadas a la vez reciben números distintos en lugar de un 409. El contador es continuo (no vuelve a 1 cada año; el año dice cuándo se creó la orden) y un borrador eliminado no devuelve su número.

### PurchaseOrderItem

| Campo             | Tipo     | Requerido | Default | Descripción                          |
| ----------------- | -------- | --------- | ------- | ------------------------------------ |
| `id`              | `int`    | auto      | —       | ID único                             |
| `purchaseOrderId` | `int`    | sí        | —       | ID de la orden de compra             |
| `productId`       | `int`    | sí        | —       | ID del producto                      |
| `productName`, `productSku` | `string?` | auto | — | Nombre y SKU del producto (solo en `GET /purchase-orders/{id}/items`) |
| `quantityOrdered` | `int`    | sí        | —       | Cantidad pedida                      |
| `quantityReceived`| `int`    | auto      | `0`     | Cantidad recibida acumulada          |
| `unitCost`        | `number` | sí        | —       | Costo unitario                       |

**Campos calculados (no vienen del API, calcular en frontend):**

| Campo             | Fórmula                               |
| ----------------- | ------------------------------------- |
| `quantityPending` | `quantityOrdered - quantityReceived`  |
| `subtotal`        | `unitCost * quantityOrdered`          |

### PurchaseReceipt

| Campo             | Tipo              | Requerido | Default | Descripción                    |
| ----------------- | ----------------- | --------- | ------- | ------------------------------ |
| `id`              | `int`             | auto      | —       | ID único                       |
| `purchaseOrderId` | `int`             | sí        | —       | ID de la orden de compra       |
| `notes`           | `string \| null`  | no        | `null`  | Notas de la recepción          |
| `receivedAt`      | `datetime \| null`| no        | `null`  | Fecha/hora de recepción        |
| `createdAt`       | `datetime \| null`| auto      | —       | Fecha de creación del registro |

### PurchaseReceiptItem

| Campo                 | Tipo              | Requerido | Default | Descripción                              |
| --------------------- | ----------------- | --------- | ------- | ---------------------------------------- |
| `id`                  | `int`             | auto      | —       | ID único                                 |
| `purchaseReceiptId`   | `int`             | auto      | —       | ID del recibo                            |
| `purchaseOrderItemId` | `int`             | sí        | —       | ID del ítem de la orden                  |
| `productId`           | `int`             | sí        | —       | ID del producto                          |
| `quantityReceived`    | `int`             | sí        | —       | Cantidad recibida en esta entrega        |
| `locationId`          | `int \| null`     | no        | `null`  | Ubicación de destino en almacén          |
| `lotNumber`           | `string \| null`  | no        | `null`  | Número de lote para trazabilidad         |
| `serialNumbers`       | `string[] \| null`| no        | `null`  | Números de serie individuales            |

---

## API Endpoints

**Base URL:** `/api/admin/purchase-orders`

### Órdenes de Compra

| Método   | Ruta              | Descripción                        |
| -------- | ----------------- | ---------------------------------- |
| `POST`   | `/`               | Crear orden de compra              |
| `GET`    | `/`               | Listar órdenes de compra           |
| `GET`    | `/{id}`           | Obtener orden por ID               |
| `PUT`    | `/{id}`           | Actualizar orden (solo en DRAFT)   |
| `DELETE` | `/{id}`           | Eliminar orden (solo en DRAFT)     |
| `POST`   | `/{id}/send`      | Enviar orden al proveedor          |
| `POST`   | `/{id}/cancel`    | Cancelar orden                     |
| `POST`   | `/{id}/receive`   | Registrar recepción de mercancía   |
| `GET`    | `/{id}/items`     | Listar ítems de la orden           |
| `GET`    | `/{id}/receipts`  | Listar recepciones de la orden     |

### Ítems de Orden de Compra

**Base URL:** `/api/admin/purchase-order-items`

| Método   | Ruta    | Descripción                               |
| -------- | ------- | ----------------------------------------- |
| `POST`   | `/`     | Agregar ítem a orden (solo en DRAFT)      |
| `PUT`    | `/{id}` | Actualizar ítem (solo si orden en DRAFT)  |
| `DELETE` | `/{id}` | Eliminar ítem (solo si orden en DRAFT)    |

---

## Detalle de Endpoints

### POST /api/admin/purchase-orders

Crea una nueva orden de compra en estado `draft`.

**Request Body:**

```json
{
  "supplierId": 5,
  "notes": "Compra de suministros Q1",
  "expectedDate": "2026-03-15T00:00:00Z"
}
```

| Campo          | Tipo              | Requerido | Validación       |
| -------------- | ----------------- | --------- | ---------------- |
| `supplierId`   | `int`             | sí        | `>= 1`           |
| `notes`        | `string \| null`  | no        | max 1024 chars   |
| `expectedDate` | `datetime \| null`| no        | formato ISO 8601 |

**Response (201):**

```json
{
  "id": 1,
  "supplierId": 5,
  "orderNumber": "PO-2026-0001",
  "status": "draft",
  "subtotal": 0,
  "tax": 0,
  "total": 0,
  "notes": "Compra de suministros Q1",
  "expectedDate": "2026-03-15T00:00:00Z",
  "createdAt": "2026-03-08T10:00:00Z",
  "updatedAt": "2026-03-08T10:00:00Z"
}
```

**Errores:**

| Código | Condición                       |
| ------ | ------------------------------- |
| 404    | Proveedor no encontrado         |
| 422    | Datos de validación inválidos   |

---

### GET /api/admin/purchase-orders

Lista órdenes de compra con filtros y paginación.

**Query Parameters:**

| Parámetro    | Tipo           | Default | Descripción                          |
| ------------ | -------------- | ------- | ------------------------------------ |
| `status`     | `string \| null` | —     | Filtrar por estado                   |
| `supplierId` | `int \| null`  | —       | Filtrar por proveedor (`>= 1`)       |
| `limit`      | `int`          | `10`    | Cantidad de resultados por página    |
| `offset`     | `int`          | `0`     | Desplazamiento para paginación       |

**Response (200):**

```json
{
  "items": [
    {
      "id": 1,
      "supplierId": 5,
      "orderNumber": "PO-2026-0001",
      "status": "draft",
      "subtotal": 1500.00,
      "tax": 0,
      "total": 1500.00,
      "notes": "Compra de suministros Q1",
      "expectedDate": "2026-03-15T00:00:00Z",
      "createdAt": "2026-03-08T10:00:00Z",
      "updatedAt": "2026-03-08T10:00:00Z"
    }
  ],
  "total": 25,
  "limit": 10,
  "offset": 0
}
```

---

### GET /api/admin/purchase-orders/{id}

Obtiene una orden de compra por su ID.

**Path Parameters:**

| Parámetro | Tipo  | Descripción            |
| --------- | ----- | ---------------------- |
| `id`      | `int` | ID de la orden         |

**Response (200):**

```json
{
  "id": 1,
  "supplierId": 5,
  "orderNumber": "PO-2026-0001",
  "status": "sent",
  "subtotal": 1500.00,
  "tax": 0,
  "total": 1500.00,
  "notes": "Compra de suministros Q1",
  "expectedDate": "2026-03-15T00:00:00Z",
  "createdAt": "2026-03-08T10:00:00Z",
  "updatedAt": "2026-03-08T12:00:00Z"
}
```

**Errores:**

| Código | Condición               |
| ------ | ----------------------- |
| 404    | Orden no encontrada     |

---

### PUT /api/admin/purchase-orders/{id}

Actualiza una orden de compra. Solo permitido cuando la orden está en estado `draft`.

**Request Body:** (mismo esquema que POST)

```json
{
  "supplierId": 7,
  "notes": "Nota actualizada",
  "expectedDate": "2026-04-01T00:00:00Z"
}
```

**Response (200):** Objeto `PurchaseOrder` actualizado.

**Errores:**

| Código | Condición                                 |
| ------ | ----------------------------------------- |
| 400    | La orden no está en estado `draft`        |
| 404    | Orden no encontrada                       |
| 422    | Datos de validación inválidos             |

---

### DELETE /api/admin/purchase-orders/{id}

Elimina una orden de compra. Solo permitido cuando la orden está en estado `draft`.

**Response (204):** Sin contenido.

**Errores:**

| Código | Condición                                 |
| ------ | ----------------------------------------- |
| 400    | La orden no está en estado `draft`        |
| 404    | Orden no encontrada                       |

---

### POST /api/admin/purchase-orders/{id}/send

Cambia el estado de la orden de `draft` a `sent`.

**Request Body:** Ninguno.

**Response (200):** Objeto `PurchaseOrder` con `status: "sent"`.

**Errores:**

| Código | Condición                                 |
| ------ | ----------------------------------------- |
| 400    | La orden no está en estado `draft`        |
| 404    | Orden no encontrada                       |

---

### POST /api/admin/purchase-orders/{id}/cancel

Cancela la orden de compra.

**Request Body:** Ninguno.

**Response (200):** Objeto `PurchaseOrder` con `status: "cancelled"`.

**Errores:**

| Código | Condición                                              |
| ------ | ------------------------------------------------------ |
| 400    | La orden está en estado `received` o `cancelled`       |
| 404    | Orden no encontrada                                    |

---

### POST /api/admin/purchase-orders/{id}/receive

Registra la recepción de mercancía. Puede ser parcial o total.

**Request Body:**

```json
{
  "items": [
    {
      "purchaseOrderItemId": 1,
      "quantityReceived": 50,
      "locationId": 10,
      "lotNumber": "LOT-2026-001",
      "serialNumbers": ["SN001", "SN002", "SN003"]
    },
    {
      "purchaseOrderItemId": 2,
      "quantityReceived": 100,
      "locationId": 10,
      "lotNumber": null,
      "serialNumbers": null
    }
  ],
  "notes": "Recibido en buenas condiciones",
  "receivedAt": "2026-03-08T10:30:00Z"
}
```

| Campo                        | Tipo              | Requerido | Validación       |
| ---------------------------- | ----------------- | --------- | ---------------- |
| `items`                      | `array`           | sí        | mínimo 1 ítem    |
| `items[].purchaseOrderItemId`| `int`             | sí        | `>= 1`           |
| `items[].quantityReceived`   | `int`             | sí        | `>= 1`           |
| `items[].locationId`         | `int \| null`     | no        | `>= 1`           |
| `items[].lotNumber`          | `string \| null`  | no        | max 64 chars     |
| `items[].serialNumbers`      | `string[] \| null`| no        | —                |
| `notes`                      | `string \| null`  | no        | max 1024 chars   |
| `receivedAt`                 | `datetime \| null`| no        | formato ISO 8601 |

**Response (201):**

```json
{
  "id": 1,
  "purchaseOrderId": 1,
  "notes": "Recibido en buenas condiciones",
  "receivedAt": "2026-03-08T10:30:00Z",
  "createdAt": "2026-03-08T10:30:00Z"
}
```

**Errores:**

| Código | Condición                                                         |
| ------ | ----------------------------------------------------------------- |
| 400    | La orden está en estado `cancelled` o `received`                  |
| 400    | La cantidad recibida excede la cantidad pendiente de algún ítem   |
| 404    | Orden no encontrada                                               |
| 422    | Datos de validación inválidos                                     |

**Efectos secundarios (automáticos):**
- Se crean movimientos de inventario tipo `IN` por cada ítem recibido
- Se actualizan las cantidades de stock en las ubicaciones correspondientes
- Si se proporciona `lotNumber`, se crea o actualiza el lote
- Si se proporcionan `serialNumbers`, se registran los números de serie
- El estado de la orden cambia a `partial` o `received` según corresponda

---

### GET /api/admin/purchase-orders/{id}/items

Lista los ítems de una orden de compra.

**Response (200):**

```json
[
  {
    "id": 1,
    "purchaseOrderId": 1,
    "productId": 10,
    "quantityOrdered": 100,
    "quantityReceived": 50,
    "unitCost": 15.00
  },
  {
    "id": 2,
    "purchaseOrderId": 1,
    "productId": 20,
    "quantityOrdered": 200,
    "quantityReceived": 200,
    "unitCost": 8.50
  }
]
```

---

### GET /api/admin/purchase-orders/{id}/receipts

Lista las recepciones de una orden de compra.

**Response (200):**

```json
[
  {
    "id": 1,
    "purchaseOrderId": 1,
    "notes": "Primera entrega parcial",
    "receivedAt": "2026-03-05T10:00:00Z",
    "createdAt": "2026-03-05T10:00:00Z"
  },
  {
    "id": 2,
    "purchaseOrderId": 1,
    "notes": "Entrega final",
    "receivedAt": "2026-03-08T14:00:00Z",
    "createdAt": "2026-03-08T14:00:00Z"
  }
]
```

---

### POST /api/admin/purchase-order-items

Agrega un ítem a una orden de compra. Solo permitido cuando la orden está en estado `draft`.

**Request Body:**

```json
{
  "purchaseOrderId": 1,
  "productId": 10,
  "quantityOrdered": 100,
  "unitCost": 15.00
}
```

| Campo             | Tipo      | Requerido | Validación |
| ----------------- | --------- | --------- | ---------- |
| `purchaseOrderId` | `int`     | sí        | `>= 1`    |
| `productId`       | `int`     | sí        | `>= 1`    |
| `quantityOrdered` | `int`     | sí        | `>= 1`    |
| `unitCost`        | `number`  | sí        | `>= 0`    |

**Response (201):**

```json
{
  "id": 1,
  "purchaseOrderId": 1,
  "productId": 10,
  "quantityOrdered": 100,
  "quantityReceived": 0,
  "unitCost": 15.00
}
```

**Efectos secundarios:** Los totales de la orden (`subtotal`, `tax`, `total`) se recalculan automáticamente.

**Errores:**

| Código | Condición                                 |
| ------ | ----------------------------------------- |
| 400    | La orden no está en estado `draft`        |
| 404    | Orden o producto no encontrado            |
| 422    | Datos de validación inválidos             |

---

### PUT /api/admin/purchase-order-items/{id}

Actualiza un ítem de orden de compra. Solo permitido cuando la orden está en estado `draft`.

**Request Body:**

```json
{
  "quantityOrdered": 150,
  "unitCost": 14.50
}
```

| Campo             | Tipo      | Requerido | Validación |
| ----------------- | --------- | --------- | ---------- |
| `quantityOrdered` | `int`     | sí        | `>= 1`    |
| `unitCost`        | `number`  | sí        | `>= 0`    |

**Response (200):** Objeto `PurchaseOrderItem` actualizado.

**Efectos secundarios:** Los totales de la orden se recalculan automáticamente.

---

### DELETE /api/admin/purchase-order-items/{id}

Elimina un ítem de orden de compra. Solo permitido cuando la orden está en estado `draft`.

**Response (204):** Sin contenido.

**Efectos secundarios:** Los totales de la orden se recalculan automáticamente.

---

## Manejo de Errores

Todas las respuestas de error siguen el formato estándar:

```json
{
  "errors": [
    {
      "code": "INVALID_PURCHASE_ORDER_STATUS",
      "message": "Cannot send a purchase order with status 'cancelled'",
      "detail": "current_status=cancelled, operation=send"
    }
  ],
  "meta": {"requestId": "abc-123-def", "timestamp": "2026-03-08T10:00:00Z"}
}
```

| Código HTTP | `errorCode`        | Casos típicos                              |
| ----------- | ------------------ | ------------------------------------------ |
| 400         | `INVALID_PURCHASE_ORDER_STATUS` | Operación no permitida en el estado actual de la orden |
| 400         | `EXCEEDS_PENDING_QUANTITY` | Recibir más unidades de las pendientes |
| 409         | `PURCHASE_ORDER_NUMBER_ALREADY_EXISTS` | Número de orden duplicado (creación concurrente) |
| 404         | `NOT_FOUND`        | Orden, ítem, proveedor o producto no existe|
| 422         | `VALIDATION_ERROR` | Campos requeridos faltantes, valores fuera de rango |

---

## Dependencias con Otros Módulos

| Módulo               | Relación                                                           |
| -------------------- | ------------------------------------------------------------------ |
| **Suppliers**        | `supplierId` referencia a un proveedor existente                   |
| **Catalog/Product**  | `productId` referencia a un producto del catálogo                  |
| **Inventory/Location** | `locationId` referencia a una ubicación de almacén (en recepción)|
| **Inventory/Movement** | Al recibir, se crean movimientos tipo `IN` automáticamente       |
| **Inventory/Stock**  | Los movimientos actualizan el stock en las ubicaciones             |
| **Inventory/Lot**    | Si se incluye `lotNumber`, se crea/actualiza el lote               |
| **Inventory/Serial** | Si se incluyen `serialNumbers`, se registran los números de serie  |

---

## Guía de Implementación Frontend

### TypeScript Types

```typescript
type PurchaseOrderStatus = 'draft' | 'sent' | 'partial' | 'received' | 'cancelled';

interface PurchaseOrder {
  id: number;
  supplierId: number;
  orderNumber: string;
  status: PurchaseOrderStatus;
  subtotal: number;
  tax: number;
  total: number;
  notes: string | null;
  expectedDate: string | null; // ISO 8601
  createdAt: string | null;
  updatedAt: string | null;
}

interface PurchaseOrderItem {
  id: number;
  purchaseOrderId: number;
  productId: number;
  quantityOrdered: number;
  quantityReceived: number;
  unitCost: number;
}

interface PurchaseReceipt {
  id: number;
  purchaseOrderId: number;
  notes: string | null;
  receivedAt: string | null;
  createdAt: string | null;
}

// --- Requests ---

interface CreatePurchaseOrderRequest {
  supplierId: number;
  notes?: string | null;
  expectedDate?: string | null;
}

interface UpdatePurchaseOrderRequest {
  supplierId: number;
  notes?: string | null;
  expectedDate?: string | null;
}

interface CreatePurchaseOrderItemRequest {
  purchaseOrderId: number;
  productId: number;
  quantityOrdered: number;
  unitCost: number;
}

interface UpdatePurchaseOrderItemRequest {
  quantityOrdered: number;
  unitCost: number;
}

interface ReceiveItemRequest {
  purchaseOrderItemId: number;
  quantityReceived: number;
  locationId?: number | null;
  lotNumber?: string | null;
  serialNumbers?: string[] | null;
}

interface CreatePurchaseReceiptRequest {
  items: ReceiveItemRequest[]; // mínimo 1
  notes?: string | null;
  receivedAt?: string | null;
}

// --- Responses ---

interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

interface ErrorResponse {
  errorCode: string;
  message: string;
  timestamp: string;
  requestId: string;
  detail: unknown | null;
}
```

### Vistas Sugeridas

#### 1. Lista de Órdenes de Compra (`/purchase-orders`)

- **Tabla** con columnas: `orderNumber`, `status` (badge con color), `supplierId` (mostrar nombre del proveedor), `total`, `expectedDate`, `createdAt`
- **Filtros**: por estado (select/tabs), por proveedor (select con búsqueda)
- **Paginación**: controles de página con `limit` y `offset`
- **Acciones por fila**: Ver detalle, Editar (solo draft), Eliminar (solo draft)
- **Botón**: "Nueva Orden de Compra"

**Colores de estado sugeridos:**

| Estado      | Color    |
| ----------- | -------- |
| `draft`     | gris     |
| `sent`      | azul     |
| `partial`   | amarillo |
| `received`  | verde    |
| `cancelled` | rojo     |

#### 2. Detalle/Edición de Orden (`/purchase-orders/{id}`)

**Sección superior - Datos de la orden:**
- Formulario con: proveedor (select), notas (textarea), fecha esperada (datepicker)
- Campos de solo lectura: `orderNumber`, `status`, `subtotal`, `tax`, `total`, `createdAt`, `updatedAt`
- Botones de acción según estado:
  - `draft`: Guardar, Enviar, Cancelar, Eliminar
  - `sent`: Recibir Mercancía, Cancelar
  - `partial`: Recibir Mercancía, Cancelar
  - `received`: Solo lectura
  - `cancelled`: Solo lectura

**Sección de ítems - Tabla de productos:**
- Columnas: producto (nombre), cantidad pedida, cantidad recibida, cantidad pendiente (calculada), costo unitario, subtotal (calculado)
- Si `draft`: botón agregar ítem, editar en línea, eliminar por fila
- Si otro estado: tabla de solo lectura
- Fila de totales al final

**Sección de recepciones (solo si estado != draft):**
- Lista/timeline de recepciones con fecha y notas
- Expandible para ver detalle de ítems recibidos por recepción

#### 3. Modal/Formulario de Agregar Ítem

- Select de producto (con búsqueda)
- Input numérico: cantidad (`>= 1`, entero)
- Input numérico: costo unitario (`>= 0`, decimal)
- Preview del subtotal calculado

#### 4. Modal/Formulario de Recepción de Mercancía (`/{id}/receive`)

- Tabla editable con los ítems pendientes de la orden
- Por cada ítem:
  - Nombre del producto (solo lectura)
  - Cantidad pedida (solo lectura)
  - Cantidad ya recibida (solo lectura)
  - Cantidad pendiente (solo lectura, calculada)
  - Input: cantidad a recibir (validar `>= 1` y `<= cantidadPendiente`)
  - Select: ubicación de destino (opcional, listar ubicaciones del almacén)
  - Input: número de lote (opcional, texto libre max 64 chars)
  - Input: números de serie (opcional, permitir agregar múltiples)
- Textarea: notas de recepción
- Datepicker: fecha de recepción (default: ahora)
- Botón: "Confirmar Recepción"

### Flujos de Usuario

#### Flujo 1: Crear y enviar una orden de compra

1. Usuario navega a `/purchase-orders` → click "Nueva Orden"
2. Selecciona proveedor, opcionalmente agrega notas y fecha esperada → Guardar
3. Sistema crea la orden en `draft` y redirige al detalle
4. Usuario agrega ítems: selecciona productos, cantidades y costos
5. Los totales se recalculan automáticamente con cada ítem agregado/modificado
6. Usuario revisa y click "Enviar" → confirmar en diálogo
7. Estado cambia a `sent`, los ítems ya no son editables

#### Flujo 2: Recibir mercancía (parcial)

1. Usuario abre una orden en estado `sent` o `partial`
2. Click "Recibir Mercancía" → se abre formulario de recepción
3. Sistema muestra los ítems con sus cantidades pendientes
4. Usuario ingresa cantidades recibidas, ubicaciones, lotes y seriales
5. Click "Confirmar Recepción"
6. Si quedan ítems pendientes → estado cambia a `partial`
7. Si todos los ítems están completos → estado cambia a `received`

#### Flujo 3: Cancelar una orden

1. Usuario abre una orden en estado `draft`, `sent` o `partial`
2. Click "Cancelar" → confirmar en diálogo de confirmación
3. Estado cambia a `cancelled`, la orden queda en solo lectura

### Consideraciones UX

- **Confirmaciones**: Siempre mostrar diálogo de confirmación para acciones de envío, cancelación y recepción
- **Validación en tiempo real**: Validar que la cantidad a recibir no exceda la cantidad pendiente antes de enviar
- **Totales en vivo**: Recalcular `subtotal` y `total` en el frontend al agregar/editar/eliminar ítems
- **Estados visuales**: Desactivar campos y ocultar botones de acción según el estado de la orden
- **Carga de datos relacionados**: Al mostrar la orden, cargar en paralelo los ítems (`GET /{id}/items`) y las recepciones (`GET /{id}/receipts`)
- **Formato de moneda**: Mostrar valores monetarios con 2 decimales y símbolo de moneda local
- **Números de serie**: Usar un componente de "tags" o "chips" para agregar/visualizar múltiples números de serie
