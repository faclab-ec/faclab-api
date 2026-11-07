# Especificación del Módulo de Reportes de Inventario

## Base URL

```
GET /api/admin/reports/inventory
```

Todos los endpoints son **solo lectura** (GET). No modifican estado.

---

## Estructura de Respuestas

Todas las respuestas usan wrappers estándar. Los campos usan **camelCase** en JSON.

### Meta (incluido en toda respuesta)

```json
{
  "requestId": "uuid-string",
  "timestamp": "2026-03-08T15:30:00"
}
```

### DataResponse\<T\> — objeto único

```json
{
  "data": { ... },
  "meta": { "requestId": "...", "timestamp": "..." }
}
```

### ListResponse\<T\> — lista sin paginación

```json
{
  "data": [ { ... }, { ... } ],
  "meta": { "requestId": "...", "timestamp": "..." }
}
```

### PaginatedDataResponse\<T\> — lista con paginación

```json
{
  "data": [ { ... }, { ... } ],
  "meta": {
    "requestId": "...",
    "timestamp": "...",
    "pagination": {
      "total": 150,
      "limit": 50,
      "offset": 0
    }
  }
}
```

### ErrorResponse (400 / 404 / 422)

```json
{
  "errors": [
    { "code": "VALIDATION_ERROR", "message": "...", "field": "warehouseId" }
  ],
  "meta": { "requestId": "...", "timestamp": "..." }
}
```

---

## 1. Valorización de Inventario

Calcula el valor monetario del inventario actual o en una fecha histórica.

### Request

```
GET /valuation
```

| Query Param   | Tipo     | Requerido | Default | Descripción                                                    |
| ------------- | -------- | --------- | ------- | -------------------------------------------------------------- |
| `warehouseId` | `int`    | No        | `null`  | Filtrar por almacén (≥ 1)                                      |
| `asOfDate`    | `date`   | No        | `null`  | Fecha histórica (formato `YYYY-MM-DD`). Si se omite, usa stock actual |

### Response — `DataResponse<InventoryValuation>`

```json
{
  "data": {
    "totalValue": 45230.50,
    "asOfDate": "2026-03-08",
    "items": [
      {
        "productId": 1,
        "productName": "Producto A",
        "sku": "PROD-001",
        "quantity": 100,
        "averageCost": 15.50,
        "totalValue": 1550.00
      }
    ]
  },
  "meta": { "requestId": "...", "timestamp": "..." }
}
```

### Campos de cada item

| Campo         | Tipo      | Descripción                             |
| ------------- | --------- | --------------------------------------- |
| `productId`   | `int`     | ID del producto                         |
| `productName` | `string`  | Nombre del producto                     |
| `sku`         | `string`  | Código SKU                              |
| `quantity`    | `decimal` | Cantidad en stock                       |
| `averageCost` | `number`  | Precio de compra (purchase_price)       |
| `totalValue`  | `number`  | quantity × averageCost                  |

### Campos del objeto principal

| Campo        | Tipo                    | Descripción                          |
| ------------ | ----------------------- | ------------------------------------ |
| `totalValue` | `number`                | Suma total del valor de inventario   |
| `asOfDate`   | `string` (YYYY-MM-DD)  | Fecha de la valorización             |
| `items`      | `ValuationItem[]`       | Lista de productos valorizados       |

### Lógica de negocio

- **Sin `asOfDate`**: Usa la tabla de stock actual. Suma cantidades por producto agrupando todas las ubicaciones.
- **Con `asOfDate`**: Reconstruye el stock histórico sumando movimientos IN y restando movimientos OUT hasta esa fecha.
- Excluye productos marcados como servicio (`isService = true`).
- Solo incluye productos con `purchasePrice > 0`.
- Si se proporciona `warehouseId`, filtra ubicaciones pertenecientes a ese almacén.

---

## 2. Rotación de Productos

Analiza la velocidad de rotación del inventario en un período de tiempo.

### Request

```
GET /rotation
```

| Query Param   | Tipo   | Requerido | Default                    | Descripción                      |
| ------------- | ------ | --------- | -------------------------- | -------------------------------- |
| `fromDate`    | `date` | No        | 1er día del mes actual     | Inicio del período (YYYY-MM-DD)  |
| `toDate`      | `date` | No        | Hoy                        | Fin del período (YYYY-MM-DD)     |
| `warehouseId` | `int`  | No        | `null`                     | Filtrar por almacén (≥ 1)        |

### Response — `ListResponse<ProductRotation>`

```json
{
  "data": [
    {
      "productId": 1,
      "productName": "Producto A",
      "sku": "PROD-001",
      "totalIn": 200,
      "totalOut": 150,
      "currentStock": 100,
      "turnoverRate": 1.50,
      "daysOfStock": 20
    }
  ],
  "meta": { "requestId": "...", "timestamp": "..." }
}
```

### Campos

| Campo          | Tipo           | Descripción                                                         |
| -------------- | -------------- | ------------------------------------------------------------------- |
| `productId`    | `int`          | ID del producto                                                     |
| `productName`  | `string`       | Nombre del producto                                                 |
| `sku`          | `string`       | Código SKU                                                          |
| `totalIn`      | `int`          | Total de movimientos de entrada en el período                       |
| `totalOut`     | `int`          | Total de movimientos de salida en el período                        |
| `currentStock` | `int`          | Stock actual del producto                                           |
| `turnoverRate` | `number`       | Tasa de rotación: `totalOut / currentStock`                         |
| `daysOfStock`  | `int \| null`  | Días de stock restantes: `currentStock / (totalOut / díasPeríodo)`. `null` si no hay salidas |

### Lógica de negocio

- Agrega movimientos IN y OUT por producto dentro del rango de fechas.
- `turnoverRate` = `totalOut / currentStock` (solo si ambos > 0, caso contrario 0).
- `daysOfStock` = `currentStock / promedioDiarioSalidas` donde `promedioDiarioSalidas = totalOut / díasDelPeríodo`. Es `null` si `totalOut = 0`.
- Excluye servicios.

---

## 3. Historial de Movimientos

Lista paginada de movimientos de inventario con filtros múltiples.

### Request

```
GET /movements
```

| Query Param   | Tipo     | Requerido | Default | Validación    | Descripción                          |
| ------------- | -------- | --------- | ------- | ------------- | ------------------------------------ |
| `limit`       | `int`    | No        | `50`    | 1–500         | Tamaño de página                     |
| `offset`      | `int`    | No        | `0`     | ≥ 0           | Desplazamiento para paginación       |
| `productId`   | `int`    | No        | `null`  | ≥ 1           | Filtrar por producto                 |
| `type`        | `string` | No        | `null`  | `"in"`, `"out"` | Filtrar por tipo de movimiento     |
| `fromDate`    | `date`   | No        | `null`  |               | Fecha inicio (YYYY-MM-DD)            |
| `toDate`      | `date`   | No        | `null`  |               | Fecha fin (YYYY-MM-DD)               |
| `warehouseId` | `int`    | No        | `null`  | ≥ 1           | Filtrar por almacén                  |

### Response — `PaginatedDataResponse<MovementHistoryItem>`

```json
{
  "data": [
    {
      "id": 42,
      "productId": 1,
      "productName": "Producto A",
      "sku": "PROD-001",
      "quantity": 10,
      "type": "out",
      "locationId": 3,
      "sourceLocationId": null,
      "referenceType": "sale",
      "referenceId": 15,
      "reason": null,
      "date": "2026-03-07T14:30:00",
      "createdAt": "2026-03-07T14:30:05"
    }
  ],
  "meta": {
    "requestId": "...",
    "timestamp": "...",
    "pagination": {
      "total": 150,
      "limit": 50,
      "offset": 0
    }
  }
}
```

### Campos

| Campo              | Tipo             | Descripción                                           |
| ------------------ | ---------------- | ----------------------------------------------------- |
| `id`               | `int`            | ID del movimiento                                     |
| `productId`        | `int`            | ID del producto                                       |
| `productName`      | `string`         | Nombre del producto                                   |
| `sku`              | `string`         | Código SKU                                            |
| `quantity`         | `decimal`        | Cantidad movida                                       |
| `type`             | `string`         | `"in"` (entrada) o `"out"` (salida)                   |
| `locationId`       | `int \| null`    | Ubicación destino                                     |
| `sourceLocationId` | `int \| null`    | Ubicación origen (para transferencias)                |
| `referenceType`    | `string \| null` | Tipo de referencia: `"sale"`, `"purchase_order"`, `"adjustment"`, `"transfer"` |
| `referenceId`      | `int \| null`    | ID de la entidad que originó el movimiento            |
| `reason`           | `string \| null` | Razón (para ajustes)                                  |
| `date`             | `datetime \| null` | Fecha del movimiento (ISO 8601)                     |
| `createdAt`        | `datetime \| null` | Fecha de creación del registro (ISO 8601)           |

### Lógica de negocio

- Todos los filtros se combinan con AND.
- Ordenado por `date` descendente (más reciente primero).
- `pagination.total` refleja el total de registros que cumplen los filtros (no solo la página actual).

---

## 4. Resumen por Almacén

Vista consolidada del inventario por almacén.

### Request

```
GET /summary
```

| Query Param   | Tipo  | Requerido | Default | Descripción                 |
| ------------- | ----- | --------- | ------- | --------------------------- |
| `warehouseId` | `int` | No        | `null`  | Filtrar almacén específico (≥ 1) |

### Response — `ListResponse<WarehouseSummary>`

```json
{
  "data": [
    {
      "warehouseId": 1,
      "warehouseName": "Almacén Central",
      "warehouseCode": "WH-001",
      "totalProducts": 45,
      "totalQuantity": 5000,
      "reservedQuantity": 200,
      "availableQuantity": 4800,
      "totalValue": 75430.00
    }
  ],
  "meta": { "requestId": "...", "timestamp": "..." }
}
```

### Campos

| Campo               | Tipo     | Descripción                                       |
| ------------------- | -------- | ------------------------------------------------- |
| `warehouseId`       | `int`    | ID del almacén                                    |
| `warehouseName`     | `string` | Nombre del almacén                                |
| `warehouseCode`     | `string` | Código del almacén                                |
| `totalProducts`     | `int`    | Cantidad de productos distintos con stock          |
| `totalQuantity`     | `decimal` | Suma de todas las cantidades en stock              |
| `reservedQuantity`  | `decimal` | Suma de cantidades reservadas                     |
| `availableQuantity` | `decimal` | `totalQuantity - reservedQuantity`                |
| `totalValue`        | `number` | Suma de `quantity × purchasePrice` por producto   |

### Lógica de negocio

- Agrega stock de todas las ubicaciones dentro de cada almacén.
- Solo incluye almacenes activos (`isActive = true`).
- Excluye servicios.
- Solo incluye registros de stock con `quantity > 0`.
- `totalValue` = Σ(quantity × product.purchasePrice).

---

## Notas para Implementación Frontend

### Tipos TypeScript

```typescript
// --- Wrappers de respuesta ---

interface Meta {
  requestId: string;
  timestamp: string;
}

interface PaginationMeta {
  total: number;
  limit: number;
  offset: number;
}

interface PaginatedMeta extends Meta {
  pagination: PaginationMeta;
}

interface DataResponse<T> {
  data: T;
  meta: Meta;
}

interface ListResponse<T> {
  data: T[];
  meta: Meta;
}

interface PaginatedDataResponse<T> {
  data: T[];
  meta: PaginatedMeta;
}

// --- Valorización ---

interface ValuationItem {
  productId: number;
  productName: string;
  sku: string;
  quantity: number;
  averageCost: number;
  totalValue: number;
}

interface InventoryValuation {
  totalValue: number;
  asOfDate: string; // YYYY-MM-DD
  items: ValuationItem[];
}

interface ValuationParams {
  warehouseId?: number;
  asOfDate?: string; // YYYY-MM-DD
}

// --- Rotación ---

interface ProductRotation {
  productId: number;
  productName: string;
  sku: string;
  totalIn: number;
  totalOut: number;
  currentStock: number;
  turnoverRate: number;
  daysOfStock: number | null;
}

interface RotationParams {
  fromDate?: string;  // YYYY-MM-DD
  toDate?: string;    // YYYY-MM-DD
  warehouseId?: number;
}

// --- Historial de Movimientos ---

interface MovementHistoryItem {
  id: number;
  productId: number;
  productName: string;
  sku: string;
  quantity: number;
  type: "in" | "out";
  locationId: number | null;
  sourceLocationId: number | null;
  referenceType: string | null;
  referenceId: number | null;
  reason: string | null;
  date: string | null;      // ISO 8601
  createdAt: string | null;  // ISO 8601
}

interface MovementHistoryParams {
  limit?: number;       // 1-500, default 50
  offset?: number;      // >= 0, default 0
  productId?: number;
  type?: "in" | "out";
  fromDate?: string;    // YYYY-MM-DD
  toDate?: string;      // YYYY-MM-DD
  warehouseId?: number;
}

// --- Resumen por Almacén ---

interface WarehouseSummary {
  warehouseId: number;
  warehouseName: string;
  warehouseCode: string;
  totalProducts: number;
  totalQuantity: number;
  reservedQuantity: number;
  availableQuantity: number;
  totalValue: number;
}

interface SummaryParams {
  warehouseId?: number;
}
```

### Ejemplo de Servicios (fetch)

```typescript
const BASE_URL = "/api/admin/reports/inventory";

async function getValuation(params?: ValuationParams): Promise<DataResponse<InventoryValuation>> {
  const query = new URLSearchParams();
  if (params?.warehouseId) query.set("warehouseId", String(params.warehouseId));
  if (params?.asOfDate) query.set("asOfDate", params.asOfDate);
  const res = await fetch(`${BASE_URL}/valuation?${query}`);
  return res.json();
}

async function getRotation(params?: RotationParams): Promise<ListResponse<ProductRotation>> {
  const query = new URLSearchParams();
  if (params?.fromDate) query.set("fromDate", params.fromDate);
  if (params?.toDate) query.set("toDate", params.toDate);
  if (params?.warehouseId) query.set("warehouseId", String(params.warehouseId));
  const res = await fetch(`${BASE_URL}/rotation?${query}`);
  return res.json();
}

async function getMovementHistory(params?: MovementHistoryParams): Promise<PaginatedDataResponse<MovementHistoryItem>> {
  const query = new URLSearchParams();
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.offset) query.set("offset", String(params.offset));
  if (params?.productId) query.set("productId", String(params.productId));
  if (params?.type) query.set("type", params.type);
  if (params?.fromDate) query.set("fromDate", params.fromDate);
  if (params?.toDate) query.set("toDate", params.toDate);
  if (params?.warehouseId) query.set("warehouseId", String(params.warehouseId));
  const res = await fetch(`${BASE_URL}/movements?${query}`);
  return res.json();
}

async function getWarehouseSummary(params?: SummaryParams): Promise<ListResponse<WarehouseSummary>> {
  const query = new URLSearchParams();
  if (params?.warehouseId) query.set("warehouseId", String(params.warehouseId));
  const res = await fetch(`${BASE_URL}/summary?${query}`);
  return res.json();
}
```

### Consideraciones de UI

| Reporte       | Componente sugerido         | Filtros principales                  |
| ------------- | --------------------------- | ------------------------------------ |
| Valorización  | Tabla + tarjeta de total    | Almacén, fecha histórica             |
| Rotación      | Tabla con badges de estado  | Rango de fechas, almacén             |
| Movimientos   | Tabla paginada              | Producto, tipo, fechas, almacén      |
| Resumen       | Cards por almacén o tabla   | Almacén                              |

- **Decimales**: Los campos `number` (averageCost, totalValue, turnoverRate) se serializan como float JSON. Formatear con 2 decimales para moneda.
- **Paginación**: Solo el historial de movimientos usa paginación. Los demás retornan listas completas.
- **Fechas**: Las fechas de query params usan formato `YYYY-MM-DD`. Las fechas en respuestas datetime usan ISO 8601.
- **Valores posibles de `referenceType`**: `"sale"`, `"purchase_order"`, `"adjustment"`, `"transfer"`.
- **Valores de `type` en movimientos**: Solo `"in"` o `"out"`.
