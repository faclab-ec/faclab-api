# Especificación del Módulo de Transferencias de Inventario

## Descripción General

El módulo de transferencias permite mover stock entre ubicaciones (locations) dentro de los almacenes. Sigue un flujo de estados (DRAFT → CONFIRMED → RECEIVED) con reserva de stock al confirmar y creación de movimientos al recibir.

---

## Máquina de Estados

```
DRAFT ──confirm──▶ CONFIRMED ──receive──▶ RECEIVED
  │                     │
  └──── cancel ────┬────┘
                   ▼
               CANCELLED
```

| Estado      | Descripción                                                        |
| ----------- | ------------------------------------------------------------------ |
| `draft`     | Borrador editable. Se pueden agregar/editar/eliminar ítems.        |
| `confirmed` | Stock reservado en origen. No se pueden modificar ítems.           |
| `received`  | Transferencia completada. Se crearon movimientos IN/OUT.           |
| `cancelled` | Cancelada. Si estaba confirmada, se liberan las reservas de stock. |

### Reglas de transición

- Solo se puede **confirmar** desde `draft` y debe tener al menos un ítem.
- Solo se puede **recibir** desde `confirmed`.
- Se puede **cancelar** desde `draft` o `confirmed` (no desde `received`).
- Solo se puede **editar/eliminar** la transferencia y sus ítems en estado `draft`.

---

## Entidades

### StockTransfer

| Campo                    | Tipo              | Requerido | Descripción                                 |
| ------------------------ | ----------------- | --------- | ------------------------------------------- |
| `id`                     | `int`             | Auto      | Identificador único                         |
| `sourceLocationId`       | `int`             | Sí        | ID de la ubicación origen                   |
| `destinationLocationId`  | `int`             | Sí        | ID de la ubicación destino                  |
| `status`                 | `TransferStatus`  | No        | Estado actual (default: `draft`)            |
| `transferDate`           | `datetime \| null` | No        | Fecha de transferencia                      |
| `requestedBy`            | `string \| null`   | No        | Persona que solicita la transferencia       |
| `notes`                  | `string \| null`   | No        | Notas adicionales                           |
| `createdAt`              | `datetime`        | Auto      | Fecha de creación                           |

**Validación**: `sourceLocationId` y `destinationLocationId` deben ser diferentes.

### StockTransferItem

| Campo        | Tipo            | Requerido | Descripción                     |
| ------------ | --------------- | --------- | ------------------------------- |
| `id`         | `int`           | Auto      | Identificador único             |
| `transferId` | `int`           | Sí        | ID de la transferencia padre    |
| `productId`  | `int`           | Sí        | ID del producto                 |
| `productName`, `productSku` | `string \| null` | Auto | Nombre y SKU del producto (solo en el listado de items) |
| `quantity`   | `int`           | Sí        | Cantidad a transferir (> 0)     |
| `lotId`      | `int \| null`    | No        | ID del lote (opcional)          |
| `notes`      | `string \| null` | No        | Notas del ítem                  |

---

## API Endpoints

**Base URL**: `/api/admin`

### Transferencias (`/transfers`)

#### Listar transferencias

```
GET /transfers?status={status}&sourceLocationId={id}&limit={n}&offset={n}
```

**Query params** (todos opcionales):

| Param              | Tipo     | Descripción                                            |
| ------------------ | -------- | ------------------------------------------------------ |
| `status`           | `string` | Filtrar por estado: `draft`, `confirmed`, `received`, `cancelled` |
| `sourceLocationId` | `int`    | Filtrar por ubicación origen (≥ 1)                     |
| `limit`            | `int`    | Cantidad por página (default: 10)                      |
| `offset`           | `int`    | Desplazamiento (default: 0)                            |

**Response** `200`:
```json
{
  "data": [
    {
      "id": 1,
      "sourceLocationId": 1,
      "destinationLocationId": 2,
      "status": "draft",
      "transferDate": null,
      "requestedBy": "Juan Pérez",
      "notes": "Reabastecimiento mensual",
      "createdAt": "2026-03-01T10:00:00"
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0
}
```

---

#### Obtener transferencia por ID

```
GET /transfers/{id}
```

**Response** `200`:
```json
{
  "data": {
    "id": 1,
    "sourceLocationId": 1,
    "destinationLocationId": 2,
    "status": "draft",
    "transferDate": null,
    "requestedBy": "Juan Pérez",
    "notes": "Reabastecimiento mensual",
    "createdAt": "2026-03-01T10:00:00"
  }
}
```

**Error** `404`: Transferencia no encontrada.

---

#### Crear transferencia

```
POST /transfers
```

**Request body**:
```json
{
  "sourceLocationId": 1,
  "destinationLocationId": 2,
  "notes": "Reabastecimiento mensual",
  "requestedBy": "Juan Pérez"
}
```

| Campo                   | Tipo            | Requerido | Validación                         |
| ----------------------- | --------------- | --------- | ---------------------------------- |
| `sourceLocationId`      | `int`           | Sí        | Debe existir                       |
| `destinationLocationId` | `int`           | Sí        | Debe existir, ≠ sourceLocationId   |
| `notes`                 | `string \| null` | No        |                                    |
| `requestedBy`           | `string \| null` | No        |                                    |

**Response** `200`:
```json
{
  "data": {
    "id": 1,
    "sourceLocationId": 1,
    "destinationLocationId": 2,
    "status": "draft",
    "transferDate": null,
    "requestedBy": "Juan Pérez",
    "notes": "Reabastecimiento mensual",
    "createdAt": "2026-03-01T10:00:00"
  }
}
```

**Error** `400`: Ubicaciones origen y destino son iguales.

---

#### Actualizar transferencia

```
PUT /transfers/{id}
```

**Request body**:
```json
{
  "notes": "Notas actualizadas",
  "requestedBy": "María López"
}
```

| Campo         | Tipo            | Requerido |
| ------------- | --------------- | --------- |
| `notes`       | `string \| null` | No        |
| `requestedBy` | `string \| null` | No        |

**Error** `400`: Solo se puede actualizar en estado `draft`.

---

#### Eliminar transferencia

```
DELETE /transfers/{id}
```

**Response** `204`: Sin contenido.

**Error** `400`: Solo se puede eliminar en estado `draft`.

---

#### Confirmar transferencia

```
POST /transfers/{id}/confirm
```

**Lógica de negocio**:
1. Verifica que la transferencia esté en estado `draft`.
2. Verifica que tenga al menos un ítem.
3. Para cada ítem, verifica que haya stock disponible suficiente en la ubicación origen.
4. Reserva el stock (incrementa `reservedQuantity` en el stock de origen).
5. Cambia el estado a `confirmed`.

**Response** `200`: Transferencia con estado `confirmed`.

**Errores**:
- `400`: No está en estado `draft`.
- `400`: No tiene ítems.
- `400`: Stock insuficiente para algún producto en la ubicación origen.

---

#### Recibir transferencia

```
POST /transfers/{id}/receive
```

**Lógica de negocio**:
1. Verifica que la transferencia esté en estado `confirmed`.
2. Para cada ítem:
   - Libera la reserva de stock en origen (decrementa `reservedQuantity`).
   - Crea un movimiento **OUT** desde la ubicación origen (cantidad negativa).
   - Crea un movimiento **IN** en la ubicación destino (cantidad positiva).
3. Los movimientos generan eventos `MovementCreated` que actualizan las cantidades de stock automáticamente.
4. Cambia el estado a `received`.

**Response** `200`: Transferencia con estado `received`.

**Error** `400`: No está en estado `confirmed`.

---

#### Cancelar transferencia

```
POST /transfers/{id}/cancel
```

**Lógica de negocio**:
1. Verifica que la transferencia NO esté en estado `received`.
2. Si estaba en estado `confirmed`, libera todas las reservas de stock en origen.
3. Cambia el estado a `cancelled`.

**Response** `200`: Transferencia con estado `cancelled`.

**Error** `400`: No se puede cancelar una transferencia ya recibida.

---

### Ítems de Transferencia

#### Agregar ítem a transferencia

```
POST /transfers/{id}/items
```

**Request body**:
```json
{
  "productId": 5,
  "quantity": 10,
  "lotId": null,
  "notes": "Unidades del lote principal"
}
```

| Campo       | Tipo            | Requerido | Validación |
| ----------- | --------------- | --------- | ---------- |
| `productId` | `int`           | Sí        |            |
| `quantity`   | `int`           | Sí        | > 0        |
| `lotId`     | `int \| null`    | No        |            |
| `notes`     | `string \| null` | No        |            |

**Response** `200`:
```json
{
  "data": {
    "id": 1,
    "transferId": 1,
    "productId": 5,
    "quantity": 10,
    "lotId": null,
    "notes": "Unidades del lote principal"
  }
}
```

**Error** `400`: Solo se pueden agregar ítems a transferencias en estado `draft`.

---

#### Listar ítems de una transferencia

```
GET /transfers/{id}/items
```

**Response** `200`:
```json
{
  "data": [
    {
      "id": 1,
      "transferId": 1,
      "productId": 5,
      "quantity": 10,
      "lotId": null,
      "notes": null
    }
  ]
}
```

---

#### Actualizar ítem (`/transfer-items`)

```
PUT /transfer-items/{id}
```

**Request body**:
```json
{
  "quantity": 15,
  "notes": "Cantidad ajustada"
}
```

| Campo      | Tipo            | Requerido | Validación |
| ---------- | --------------- | --------- | ---------- |
| `quantity` | `int \| null`    | No        | > 0        |
| `notes`    | `string \| null` | No        |            |

**Response** `200`: Ítem actualizado.

---

#### Eliminar ítem (`/transfer-items`)

```
DELETE /transfer-items/{id}
```

**Response** `204`: Sin contenido.

---

## Flujo Completo (Ejemplo Frontend)

### 1. Crear transferencia (borrador)

```
POST /api/admin/transfers
Body: { "sourceLocationId": 1, "destinationLocationId": 3 }
→ Respuesta: transfer con id=7, status="draft"
```

### 2. Agregar ítems

```
POST /api/admin/transfers/7/items
Body: { "productId": 10, "quantity": 50 }
→ Respuesta: item con id=1

POST /api/admin/transfers/7/items
Body: { "productId": 22, "quantity": 100, "lotId": 3 }
→ Respuesta: item con id=2
```

### 3. Confirmar (reserva stock)

```
POST /api/admin/transfers/7/confirm
→ Respuesta: transfer con status="confirmed"
```

> En este punto el stock disponible en origen se reduce (se reserva), pero aún no se ha movido.

### 4. Recibir (ejecuta movimientos)

```
POST /api/admin/transfers/7/receive
→ Respuesta: transfer con status="received"
```

> Se crean movimientos OUT en origen e IN en destino. El stock se actualiza automáticamente.

### Flujo alternativo: Cancelar

```
POST /api/admin/transfers/7/cancel
→ Si estaba confirmed, libera reservas. Estado pasa a "cancelled".
```

---

## Formato JSON (camelCase)

Todos los campos en request y response usan **camelCase**:

| Backend (snake_case)       | JSON (camelCase)          |
| -------------------------- | ------------------------- |
| `source_location_id`       | `sourceLocationId`        |
| `destination_location_id`  | `destinationLocationId`   |
| `transfer_date`            | `transferDate`            |
| `requested_by`             | `requestedBy`             |
| `created_at`               | `createdAt`               |
| `transfer_id`              | `transferId`              |
| `product_id`               | `productId`               |
| `lot_id`                   | `lotId`                   |

---

## Errores Comunes

| Código | Situación                                                 |
| ------ | --------------------------------------------------------- |
| `400`  | Ubicaciones origen y destino son iguales                  |
| `400`  | Transferencia no está en estado válido para la operación  |
| `400`  | No tiene ítems al intentar confirmar                      |
| `400`  | Stock insuficiente al confirmar                           |
| `400`  | No se puede cancelar una transferencia recibida           |
| `404`  | Transferencia o ítem no encontrado                        |
| `422`  | Validación de campos (quantity ≤ 0, campos faltantes)     |

**Formato de error**:
```json
{
  "errors": [
    {
      "code": "INVALID_TRANSFER_STATUS",
      "message": "No se puede confirmar una transferencia en estado received",
      "detail": "current_status=received, operation=confirmar"
    }
  ],
  "meta": {"requestId": "abc-123", "timestamp": "2026-03-01T10:00:00Z"}
}
```

Códigos: `INVALID_TRANSFER_STATUS` (operación no permitida en el estado actual), `TRANSFER_HAS_NO_ITEMS`, `INSUFFICIENT_STOCK` (400) y `VALIDATION_ERROR` (422, incluye origen igual a destino).

---

## Interacción con Otros Módulos

```
                    ┌─────────────┐
                    │  Locations   │ ← sourceLocationId / destinationLocationId
                    └─────────────┘
                          ▲
    ┌─────────────────────┼─────────────────────┐
    │              StockTransfer                 │
    │  (confirm → reserva stock)                │
    │  (receive → crea movimientos IN/OUT)      │
    │  (cancel  → libera reservas si confirmed) │
    └─────────────────────┬─────────────────────┘
                          │
              ┌───────────┼───────────┐
              ▼                       ▼
       ┌───────────┐          ┌──────────────┐
       │   Stock    │          │  Movements   │
       │ (reserved  │          │ (OUT origen, │
       │  quantity) │          │  IN destino) │
       └───────────┘          └──────┬───────┘
                                     │
                              MovementCreated
                                     │
                                     ▼
                              ┌───────────┐
                              │   Stock    │
                              │ (quantity  │
                              │  updated)  │
                              └───────────┘
```

- **Stock**: Se lee y modifica `reservedQuantity` durante confirm/cancel.
- **Movement**: Se crean movimientos con `referenceType="transfer"` y `referenceId=transferId` al recibir.
- **Location**: Las ubicaciones deben existir previamente.
- **Product**: Los productos referenciados en los ítems deben existir.
- **Lot** (opcional): Si se especifica `lotId`, debe existir.
