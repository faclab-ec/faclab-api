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

## Costo de inventario (S5.6)

Cada movimiento guarda su costo por unidad base (`unitCost`) y cada fila de stock
su **costo promedio ponderado** (`averageCost`, `GET /api/admin/stock`). El
promedio vive en la fila (producto, ubicación): la que bloquea toda entrada y
salida, así que se recalcula sin bloqueos nuevos. El costo y el valor por bodega
se derivan: valor = Σ cantidad × costo de cada ubicación; promedio = valor /
cantidad. Con una ubicación por bodega (lo que crea el aprovisionamiento) es lo
mismo que un promedio por bodega.

**Toda entrada recalcula el promedio con su costo; toda salida sale al promedio
vigente y no lo cambia.** Promedio nuevo = (Q · promedio + q · costo) / (Q + q),
a 6 decimales con la mitad hacia arriba; sin existencias queda el costo de la
entrada.

| Flujo | Costo del movimiento |
| --- | --- |
| Recepción de compra (IN) | Costo de la línea / factor de su presentación (una caja de 12 a 30,00 pone cada unidad a 2,50). Sin IVA |
| Venta del POS (OUT) | Promedio de la ubicación del terminal |
| Anulación o devolución del POS (IN) | El costo con que salió de la venta |
| Transferencia | OUT del origen a su promedio; el destino recibe a ese costo |
| Ajuste | Lo que el conteo quita sale al promedio; lo que agrega entra al `unitCost` del ítem (saldos iniciales) o, sin él, al promedio |
| Movimiento manual | OUT al promedio (no acepta `unitCost`); IN al `unitCost` enviado o, sin él, al promedio |

Una entrada sin costo en una ubicación que nunca tuvo el producto toma su precio
de compra, o 0. Los movimientos y el stock anteriores a S5.6 quedaron con el
precio de compra del producto (migración `720f0fa5fb74`).

---

## 1. Valorización de Inventario

Calcula el valor del inventario al costo promedio ponderado, actual o en una
fecha histórica.

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
| `averageCost` | `number`  | Costo promedio ponderado por unidad base: `totalValue / quantity`, ponderado entre las ubicaciones |
| `totalValue`  | `number`  | Valor: Σ cantidad × costo promedio de cada ubicación |

### Campos del objeto principal

| Campo        | Tipo                    | Descripción                          |
| ------------ | ----------------------- | ------------------------------------ |
| `totalValue` | `number`                | Suma total del valor de inventario   |
| `asOfDate`   | `string` (YYYY-MM-DD)  | Fecha de la valorización             |
| `items`      | `ValuationItem[]`       | Lista de productos valorizados       |

### Lógica de negocio

- **Sin `asOfDate`**: Usa la tabla de stock actual: por producto, Σ cantidad y Σ cantidad × `averageCost` de cada ubicación.
- **Con `asOfDate`**: Reconstruye el stock y su valor con los movimientos hasta esa fecha: Σ cantidad y Σ cantidad × `unitCost` (las salidas restan). Coincide con el saldo final del kárdex a esa fecha.
- Excluye productos marcados como servicio (`isService = true`).
- Solo incluye productos con cantidad > 0. Un producto sin costo aparece con valor 0 (antes de S5.6 se omitían los productos sin precio de compra).
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
      "createdAt": "2026-03-07T14:30:05",
      "unitCost": 6.5
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
| `unitCost`         | `number`         | Costo por unidad base con que se movió (una salida: el promedio de su ubicación) |

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
| `totalValue`        | `number` | Σ `quantity × averageCost` de las filas de stock    |

### Lógica de negocio

- Agrega stock de todas las ubicaciones dentro de cada almacén.
- Solo incluye almacenes activos (`isActive = true`).
- Excluye servicios.
- Solo incluye registros de stock con `quantity > 0`.
- `totalValue` = Σ(quantity × averageCost) de cada fila de stock (S5.6).

---

## 5. Kárdex valorizado (S5.6)

Entradas, salidas y saldos de un producto, en cantidad y valor, en una bodega (o
en todas las ubicaciones).

### Request

```
GET /kardex
```

| Query Param   | Tipo   | Requerido | Default                      | Descripción |
| ------------- | ------ | --------- | ---------------------------- | ----------- |
| `productId`   | `int`  | Sí        |                              | Producto (≥ 1) |
| `warehouseId` | `int`  | No        | `null`                       | Bodega; sin ella, todas las ubicaciones |
| `fromDate`    | `date` | No        | Primer día del mes actual    | Desde (inclusive) |
| `toDate`      | `date` | No        | Hoy                          | Hasta (inclusive) |

### Response — `DataResponse<Kardex>`

```json
{
  "data": {
    "productId": 1,
    "productName": "Cemento 50 kg",
    "sku": "CEM-50",
    "warehouseId": 1,
    "fromDate": "2026-04-01",
    "toDate": "2026-04-30",
    "opening": { "quantity": 25, "value": 162.5, "averageCost": 6.5 },
    "entries": [
      {
        "movementId": 4,
        "date": "2026-04-02T10:00:00",
        "type": "OUT",
        "locationId": 1,
        "locationName": "Percha",
        "referenceType": "transfer",
        "referenceId": 3,
        "reason": "Transferencia #3 - salida de origen",
        "inQuantity": 0,
        "outQuantity": 5,
        "unitCost": 6.5,
        "value": 32.5,
        "balanceQuantity": 20,
        "balanceValue": 130.0,
        "averageCost": 6.5
      }
    ],
    "totalIn": { "quantity": 0, "value": 0 },
    "totalOut": { "quantity": 5, "value": 32.5 },
    "closing": { "quantity": 20, "value": 130.0, "averageCost": 6.5 }
  },
  "meta": { "requestId": "...", "timestamp": "..." }
}
```

### Lógica de negocio

- `opening`: Σ cantidad y Σ cantidad × `unitCost` de los movimientos antes de `fromDate`.
- `entries`: los movimientos del período, ordenados por fecha e id, con el saldo acumulado después de cada uno. `value` = cantidad × `unitCost` (sin signo); `averageCost` = saldo en valor / saldo en cantidad (`null` sin existencias).
- `closing` = `opening` + `totalIn` − `totalOut`, en cantidad y en valor; con la bodega completa coincide con la valorización de esa bodega.
- Con `warehouseId`, toma los movimientos de sus ubicaciones: una transferencia entre dos de ellas aparece como salida y entrada al mismo costo (se compensan).
- Cantidades en unidades base. Producto o bodega inexistentes (u otra empresa): `NOT_FOUND`.
- Sin paginación: un producto en un rango de fechas.

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
  unitCost: number;
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

// --- Kárdex ---

interface KardexBalance {
  quantity: number;
  value: number;
  averageCost: number | null;
}

interface KardexEntry {
  movementId: number;
  date: string | null;
  type: "IN" | "OUT";
  locationId: number | null;
  locationName: string | null;
  referenceType: string | null;
  referenceId: number | null;
  reason: string | null;
  inQuantity: number;
  outQuantity: number;
  unitCost: number;
  value: number;
  balanceQuantity: number;
  balanceValue: number;
  averageCost: number | null;
}

interface Kardex {
  productId: number;
  productName: string;
  sku: string;
  warehouseId: number | null;
  fromDate: string;
  toDate: string;
  opening: KardexBalance;
  entries: KardexEntry[];
  totalIn: { quantity: number; value: number };
  totalOut: { quantity: number; value: number };
  closing: KardexBalance;
}

interface KardexParams {
  productId: number;
  warehouseId?: number;
  fromDate?: string;
  toDate?: string;
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
| Kárdex        | Saldos + tabla con saldo acumulado | Producto, almacén, fechas     |

- **Decimales**: Los campos `number` (averageCost, totalValue, unitCost, turnoverRate) se serializan como float JSON. Formatear con 2 decimales para moneda; los costos unitarios guardan hasta 6.
- **Paginación**: Solo el historial de movimientos usa paginación. Los demás retornan listas completas.
- **Fechas**: Las fechas de query params usan formato `YYYY-MM-DD`. Las fechas en respuestas datetime usan ISO 8601.
- **Valores posibles de `referenceType`**: `"sale"`, `"refund"`, `"purchase_order"`, `"adjustment"`, `"transfer"`; `null` en un movimiento manual.
- **Valores de `type` en movimientos**: Solo `"in"` o `"out"`.
