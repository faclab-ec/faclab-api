# Especificacion del Modulo de Ajustes de Inventario

## Descripcion General

El modulo de Ajustes de Inventario permite realizar conteos fisicos, correcciones y bajas de stock. Sigue un ciclo de vida DRAFT -> CONFIRMED / CANCELLED. Al confirmar, genera movimientos de inventario automaticos que actualizan el stock.

---

## Enums

### AdjustmentStatus

| Valor        | Descripcion                  |
|--------------|------------------------------|
| `draft`      | Borrador, editable           |
| `confirmed`  | Confirmado, genera movimientos |
| `cancelled`  | Cancelado, sin efecto        |

### AdjustmentReason

| Valor            | Descripcion                    |
|------------------|--------------------------------|
| `physical_count` | Conteo fisico                  |
| `damaged`        | Productos danados              |
| `theft`          | Robo                           |
| `expiration`     | Productos vencidos             |
| `supplier_error` | Error del proveedor            |
| `correction`     | Correccion general             |
| `other`          | Otros                          |

---

## Entidades

### InventoryAdjustment

| Campo             | Tipo               | Requerido | Default   | Descripcion                    |
|-------------------|--------------------|-----------|-----------|---------------------------------|
| `id`              | int                | Auto      | -         | ID primario                     |
| `warehouseId`     | int                | Si        | -         | FK a warehouse                  |
| `reason`          | AdjustmentReason   | Si        | -         | Motivo del ajuste               |
| `status`          | AdjustmentStatus   | No        | `draft`   | Estado actual                   |
| `adjustmentDate`  | datetime \| null   | No        | null      | Fecha del ajuste                |
| `notes`           | string \| null     | No        | null      | Observaciones                   |
| `adjustedBy`      | string \| null     | No        | null      | Persona que realizo el ajuste   |
| `createdAt`       | datetime \| null   | Auto      | now       | Fecha de creacion               |

### AdjustmentItem

| Campo              | Tipo           | Requerido | Default | Descripcion                        |
|--------------------|----------------|-----------|---------|------------------------------------|
| `id`               | int            | Auto      | -       | ID primario                        |
| `adjustmentId`     | int            | Si        | -       | FK a InventoryAdjustment           |
| `productId`        | int            | Si        | -       | FK a Product                       |
| `locationId`       | int            | Si        | -       | FK a Location                      |
| `expectedQuantity` | int            | Auto      | -       | Cantidad en sistema (capturada al agregar item) |
| `actualQuantity`   | int            | Si        | -       | Cantidad contada/real              |
| `difference`       | int            | Calculado | -       | `actualQuantity - expectedQuantity` |
| `lotId`            | int \| null    | No        | null    | FK a Lot (opcional)                |
| `notes`            | string \| null | No        | null    | Observaciones del item             |

> **Nota:** `expectedQuantity` lo asigna el backend automaticamente consultando el stock actual del producto en la ubicacion. No se envia desde el frontend.

> **Nota:** `difference` es calculado: positivo = sobrante, negativo = faltante.

---

## Endpoints API

Base URL: `/api/admin`

### Ajustes

| Metodo | Ruta                           | Descripcion                       |
|--------|--------------------------------|-----------------------------------|
| GET    | `/adjustments`                 | Listar ajustes (paginado + filtros) |
| POST   | `/adjustments`                 | Crear ajuste en DRAFT             |
| GET    | `/adjustments/{id}`            | Obtener ajuste por ID             |
| PUT    | `/adjustments/{id}`            | Actualizar ajuste (solo DRAFT)    |
| DELETE | `/adjustments/{id}`            | Eliminar ajuste (solo DRAFT)      |
| POST   | `/adjustments/{id}/confirm`    | Confirmar ajuste                  |
| POST   | `/adjustments/{id}/cancel`     | Cancelar ajuste (solo DRAFT)      |
| POST   | `/adjustments/{id}/items`      | Agregar item al ajuste            |
| GET    | `/adjustments/{id}/items`      | Listar items del ajuste           |

### Items de Ajuste

| Metodo | Ruta                          | Descripcion              |
|--------|-------------------------------|--------------------------|
| PUT    | `/adjustment-items/{id}`      | Actualizar item          |
| DELETE | `/adjustment-items/{id}`      | Eliminar item            |

---

## Schemas de Request/Response

> Todos los campos usan **camelCase** en JSON.

### CreateAdjustmentRequest (POST `/adjustments`)

```json
{
  "warehouseId": 1,
  "reason": "physical_count",
  "notes": "Conteo mensual",
  "adjustedBy": "Juan Perez"
}
```

| Campo         | Tipo           | Requerido |
|---------------|----------------|-----------|
| `warehouseId` | int            | Si        |
| `reason`      | string (enum)  | Si        |
| `notes`       | string \| null | No        |
| `adjustedBy`  | string \| null | No        |

### UpdateAdjustmentRequest (PUT `/adjustments/{id}`)

```json
{
  "notes": "Conteo actualizado",
  "adjustedBy": "Maria Lopez"
}
```

| Campo       | Tipo           | Requerido |
|-------------|----------------|-----------|
| `notes`     | string \| null | No        |
| `adjustedBy`| string \| null | No        |

> Solo funciona si el ajuste esta en `draft`. Retorna 400 si no lo esta.

### AddAdjustmentItemRequest (POST `/adjustments/{id}/items`)

```json
{
  "productId": 5,
  "locationId": 2,
  "actualQuantity": 48,
  "lotId": null,
  "notes": "Faltan 2 unidades"
}
```

| Campo            | Tipo           | Requerido |
|------------------|----------------|-----------|
| `productId`      | int            | Si        |
| `locationId`     | int            | Si        |
| `actualQuantity` | int            | Si        |
| `lotId`          | int \| null    | No        |
| `notes`          | string \| null | No        |

> El backend consulta el stock actual y asigna `expectedQuantity` automaticamente.

### UpdateAdjustmentItemRequest (PUT `/adjustment-items/{id}`)

```json
{
  "actualQuantity": 50,
  "notes": "Correccion de conteo"
}
```

| Campo            | Tipo           | Requerido |
|------------------|----------------|-----------|
| `actualQuantity` | int \| null    | No        |
| `notes`          | string \| null | No        |

### AdjustmentResponse

```json
{
  "id": 1,
  "warehouseId": 1,
  "reason": "physical_count",
  "status": "draft",
  "adjustmentDate": null,
  "notes": "Conteo mensual",
  "adjustedBy": "Juan Perez",
  "createdAt": "2026-03-08T10:30:00"
}
```

### AdjustmentItemResponse

```json
{
  "id": 1,
  "adjustmentId": 1,
  "productId": 5,
  "locationId": 2,
  "expectedQuantity": 50,
  "actualQuantity": 48,
  "difference": -2,
  "lotId": null,
  "notes": "Faltan 2 unidades"
}
```

### Listado paginado (GET `/adjustments`)

**Query params:**

| Param         | Tipo           | Descripcion              |
|---------------|----------------|--------------------------|
| `status`      | string \| null | Filtrar por estado       |
| `warehouseId` | int \| null    | Filtrar por almacen (>= 1) |
| `limit`       | int \| null    | Limite de resultados     |
| `offset`      | int \| null    | Desplazamiento           |

**Response:**

```json
{
  "data": {
    "items": [ /* AdjustmentResponse[] */ ],
    "total": 25,
    "limit": 10,
    "offset": 0
  }
}
```

### Listado de items (GET `/adjustments/{id}/items`)

```json
{
  "data": [ /* AdjustmentItemResponse[] */ ]
}
```

---

## Ciclo de Vida y Reglas de Negocio

### Diagrama de Estados

```
  ┌─────────┐    confirmar    ┌────────────┐
  │  DRAFT  │ ──────────────> │  CONFIRMED │
  │         │                 └────────────┘
  │         │    cancelar     ┌────────────┐
  │         │ ──────────────> │  CANCELLED │
  └─────────┘                 └────────────┘
```

### Reglas

1. **Solo en DRAFT** se puede: editar, eliminar, cancelar, agregar/editar/eliminar items.
2. **Confirmar** solo desde DRAFT:
   - Cambia estado a `confirmed`.
   - Por cada item con `difference != 0`, genera un movimiento de inventario:
     - `difference > 0` (sobrante) -> movimiento tipo `IN`
     - `difference < 0` (faltante) -> movimiento tipo `OUT`
     - `difference == 0` -> no genera movimiento
   - Los movimientos actualizan el stock automaticamente via eventos.
3. **Cancelar** solo desde DRAFT -> cambia a `cancelled`, sin efecto en stock.
4. Un ajuste CONFIRMED no se puede modificar ni cancelar.
5. `expectedQuantity` se congela al momento de agregar el item (snapshot del stock actual).

### Logica de Movimientos al Confirmar

Para cada item del ajuste:

```
difference = actualQuantity - expectedQuantity

Si difference > 0:  movimiento IN  con cantidad = difference
Si difference < 0:  movimiento OUT con cantidad = abs(difference)
Si difference == 0: sin movimiento
```

Referencia del movimiento: `referenceType = "adjustment"`, `referenceId = adjustment.id`.

---

## Errores

| Codigo HTTP | Condicion                                       |
|-------------|-------------------------------------------------|
| 400         | Intentar confirmar un ajuste que no esta en DRAFT |
| 400         | Intentar cancelar un ajuste ya confirmado         |
| 400         | Intentar editar/eliminar un ajuste no DRAFT       |
| 400         | Intentar agregar items a un ajuste no DRAFT       |
| 404         | Ajuste no encontrado                              |
| 404         | Item de ajuste no encontrado                      |

Formato de error:

```json
{
  "errors": [
    {
      "code": "INVALID_ADJUSTMENT_STATUS",
      "message": "No se puede confirmar un ajuste en estado confirmed",
      "detail": "current_status=confirmed, operation=confirmar"
    }
  ],
  "meta": {"requestId": "uuid", "timestamp": "2026-03-08T10:30:00Z"}
}
```

Todas las operaciones fuera de DRAFT responden 400 con `INVALID_ADJUSTMENT_STATUS`.

---

## Dependencias con Otros Modulos

| Modulo      | Relacion                                                    |
|-------------|-------------------------------------------------------------|
| Warehouse   | `warehouseId` referencia al almacen                         |
| Location    | `locationId` en items referencia ubicaciones del almacen    |
| Product     | `productId` en items referencia el producto                 |
| Stock       | Se consulta para obtener `expectedQuantity` al agregar item |
| Movement    | Se crean movimientos IN/OUT al confirmar el ajuste          |
| Lot         | `lotId` opcional para items con trazabilidad por lote       |

---

## Guia de Implementacion Frontend

### Vistas Sugeridas

1. **Lista de Ajustes** (`/adjustments`)
   - Tabla paginada con columnas: ID, Almacen, Motivo, Estado, Fecha, Responsable
   - Filtros por estado y almacen
   - Badges de color por estado: draft=gris, confirmed=verde, cancelled=rojo
   - Boton "Nuevo Ajuste"

2. **Detalle/Edicion de Ajuste** (`/adjustments/{id}`)
   - Header con datos del ajuste (almacen, motivo, notas, responsable)
   - Tabla de items con: Producto, Ubicacion, Esperado, Actual, Diferencia, Lote, Notas
   - Colorear diferencia: verde si > 0 (sobrante), rojo si < 0 (faltante), gris si 0
   - Acciones segun estado:
     - DRAFT: Editar, Agregar Item, Confirmar, Cancelar, Eliminar
     - CONFIRMED: Solo lectura
     - CANCELLED: Solo lectura

3. **Formulario Crear Ajuste**
   - Select de almacen (GET `/api/admin/warehouses`)
   - Select de motivo (enum AdjustmentReason)
   - Campo notas (textarea)
   - Campo responsable (text)

4. **Formulario Agregar Item**
   - Select de producto (GET `/api/admin/products`)
   - Select de ubicacion (GET `/api/admin/locations?warehouseId={id}`)
   - Input cantidad actual (number)
   - Select de lote (opcional, GET `/api/admin/lots?productId={id}`)
   - Campo notas (textarea)
   - Al guardar, el response incluye `expectedQuantity` y `difference` calculados

### Flujo de Usuario Tipico

```
1. Crear ajuste (seleccionar almacen + motivo)
2. Agregar items uno por uno:
   - Seleccionar producto y ubicacion
   - Ingresar cantidad contada (actualQuantity)
   - El sistema muestra expectedQuantity y difference
3. Revisar diferencias
4. Confirmar ajuste -> stock se actualiza automaticamente
```

### Consideraciones de UX

- Deshabilitar edicion y acciones de escritura cuando `status !== "draft"`
- Mostrar dialogo de confirmacion antes de confirmar/cancelar/eliminar
- Al confirmar, mostrar resumen de movimientos que se generaran (items con diferencia != 0)
- El campo `expectedQuantity` es de solo lectura (lo asigna el backend)
- Refrescar la lista de items despues de agregar/editar/eliminar
