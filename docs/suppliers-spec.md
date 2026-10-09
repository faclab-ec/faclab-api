# Suppliers Module - Frontend Specification

## Base URL

```
/api/admin
```

## Serialization

- **Request**: acepta tanto `camelCase` como `snake_case` en el body JSON.
- **Response**: siempre serializa en `camelCase`.

---

## 1. Proveedores (Suppliers)

### 1.1 Crear proveedor

```
POST /suppliers
```

**Request Body:**

```json
{
  "name": "Proveedor ABC",
  "taxId": "1234567890001",
  "taxType": 1,
  "email": "contacto@abc.com",
  "phone": "0991234567",
  "address": "Av. Principal 123",
  "city": "Quito",
  "country": "EC",
  "paymentTerms": 30,
  "leadTimeDays": 7,
  "isActive": true,
  "notes": "Proveedor principal de insumos"
}
```

| Campo          | Tipo           | Requerido | Validaciones                                          |
| -------------- | -------------- | --------- | ----------------------------------------------------- |
| name           | string         | Si        | min: 1, max: 128 caracteres                           |
| taxId          | string         | Si        | min: 1, max: 32 caracteres                            |
| taxType        | int            | No        | 1-4. Default: 1. (1=RUC, 2=CEDULA, 3=PASAPORTE, 4=EXTRANJERO) |
| email          | string \| null | No        | max: 128 caracteres                                   |
| phone          | string \| null | No        | max: 32 caracteres                                    |
| address        | string \| null | No        | max: 255 caracteres                                   |
| city           | string \| null | No        | max: 64 caracteres                                    |
| country        | string \| null | No        | max: 64 caracteres                                    |
| paymentTerms   | int \| null    | No        | >= 0 (dias de credito)                                |
| leadTimeDays   | int \| null    | No        | >= 0 (dias de entrega)                                |
| isActive       | bool           | No        | Default: true                                         |
| notes          | string \| null | No        | max: 512 caracteres                                   |

**Response: `201`**

```json
{
  "data": {
    "id": 1,
    "name": "Proveedor ABC",
    "taxId": "1234567890001",
    "taxType": 1,
    "email": "contacto@abc.com",
    "phone": "0991234567",
    "address": "Av. Principal 123",
    "city": "Quito",
    "country": "EC",
    "paymentTerms": 30,
    "leadTimeDays": 7,
    "isActive": true,
    "notes": "Proveedor principal de insumos"
  },
  "meta": {
    "requestId": "uuid-string",
    "timestamp": "2026-03-07T12:00:00.000Z"
  }
}
```

---

### 1.2 Listar proveedores (paginado)

```
GET /suppliers
```

**Query Params:**

| Param    | Tipo         | Default | Descripcion                    |
| -------- | ------------ | ------- | ------------------------------ |
| limit    | int          | 100     | 1-1000                         |
| offset   | int          | 0       | >= 0                           |
| isActive | bool \| null | null    | Filtra por estado activo/inactivo |
| search   | string \| null | null  | Texto contenido en el nombre o la identificación (sin distinguir mayúsculas) |

**Response: `200`**

```json
{
  "data": [
    {
      "id": 1,
      "name": "Proveedor ABC",
      "taxId": "1234567890001",
      "taxType": 1,
      "email": "contacto@abc.com",
      "phone": "0991234567",
      "address": "Av. Principal 123",
      "city": "Quito",
      "country": "EC",
      "paymentTerms": 30,
      "leadTimeDays": 7,
      "isActive": true,
      "notes": null
    }
  ],
  "meta": {
    "requestId": "uuid-string",
    "timestamp": "2026-03-07T12:00:00.000Z",
    "pagination": {
      "total": 42,
      "limit": 100,
      "offset": 0
    }
  }
}
```

---

### 1.3 Obtener proveedor por ID

```
GET /suppliers/{id}
```

**Path Params:** `id` (int) - ID del proveedor

**Response: `200`** - Mismo formato que crear (`DataResponse[SupplierResponse]`)

**Error: `404`** - Proveedor no encontrado

---

### 1.4 Actualizar proveedor

```
PUT /suppliers/{id}
```

**Path Params:** `id` (int) - ID del proveedor

**Request Body:** Mismo schema que crear (todos los campos se envian, no es PATCH)

**Response: `200`** - `DataResponse[SupplierResponse]`

**Error: `404`** - Proveedor no encontrado

---

### 1.5 Eliminar proveedor

```
DELETE /suppliers/{id}
```

**Path Params:** `id` (int) - ID del proveedor

**Response: `204`** - Sin contenido (elimina tambien contactos y productos asociados por cascade)

---

### 1.6 Activar proveedor

```
POST /suppliers/{id}/activate
```

**Path Params:** `id` (int) - ID del proveedor

**Request Body:** ninguno

**Response: `200`** - `DataResponse[SupplierResponse]` con `isActive: true`

**Error: `404`** - Proveedor no encontrado

---

### 1.7 Desactivar proveedor

```
POST /suppliers/{id}/deactivate
```

**Path Params:** `id` (int) - ID del proveedor

**Request Body:** ninguno

**Response: `200`** - `DataResponse[SupplierResponse]` con `isActive: false`

**Error: `404`** - Proveedor no encontrado

---

## 2. Contactos de Proveedor (Supplier Contacts)

### 2.1 Crear contacto

```
POST /suppliers/{supplier_id}/contacts
```

**Path Params:** `supplier_id` (int) - ID del proveedor

**Request Body:**

```json
{
  "name": "Juan Perez",
  "role": "Gerente de ventas",
  "email": "juan@abc.com",
  "phone": "0991112233"
}
```

| Campo | Tipo           | Requerido | Validaciones        |
| ----- | -------------- | --------- | ------------------- |
| name  | string         | Si        | min: 1, max: 128    |
| role  | string \| null | No        | max: 64 caracteres  |
| email | string \| null | No        | max: 128 caracteres |
| phone | string \| null | No        | max: 32 caracteres  |

**Response: `200`**

```json
{
  "data": {
    "id": 1,
    "supplierId": 5,
    "name": "Juan Perez",
    "role": "Gerente de ventas",
    "email": "juan@abc.com",
    "phone": "0991112233"
  },
  "meta": {
    "requestId": "uuid-string",
    "timestamp": "2026-03-07T12:00:00.000Z"
  }
}
```

---

### 2.2 Listar contactos de un proveedor

```
GET /suppliers/{supplier_id}/contacts
```

**Path Params:** `supplier_id` (int) - ID del proveedor

**Response: `200`**

```json
{
  "data": [
    {
      "id": 1,
      "supplierId": 5,
      "name": "Juan Perez",
      "role": "Gerente de ventas",
      "email": "juan@abc.com",
      "phone": "0991112233"
    }
  ],
  "meta": {
    "requestId": "uuid-string",
    "timestamp": "2026-03-07T12:00:00.000Z"
  }
}
```

---

### 2.3 Obtener contacto por ID

```
GET /supplier-contacts/{id}
```

**Path Params:** `id` (int) - ID del contacto

**Response: `200`** - `DataResponse[SupplierContactResponse]`

**Error: `404`** - Contacto no encontrado

---

### 2.4 Actualizar contacto

```
PUT /supplier-contacts/{id}
```

**Path Params:** `id` (int) - ID del contacto

**Request Body:** Mismo schema que crear contacto

**Response: `200`** - `DataResponse[SupplierContactResponse]`

---

### 2.5 Eliminar contacto

```
DELETE /supplier-contacts/{id}
```

**Path Params:** `id` (int) - ID del contacto

**Response: `204`** - Sin contenido

---

## 3. Productos de Proveedor (Supplier Products)

Asocia productos del catalogo con un proveedor (precio de compra, SKU del proveedor, etc.)

### 3.1 Agregar producto al catalogo del proveedor

```
POST /suppliers/{supplier_id}/products
```

**Path Params:** `supplier_id` (int) - ID del proveedor (se usa del path, no del body)

**Request Body:**

```json
{
  "productId": 10,
  "purchasePrice": 25.50,
  "supplierSku": "ABC-001",
  "minOrderQuantity": 5,
  "leadTimeDays": 3,
  "isPreferred": true
}
```

| Campo            | Tipo           | Requerido | Validaciones        |
| ---------------- | -------------- | --------- | ------------------- |
| productId        | int            | Si        | >= 1                |
| purchasePrice    | decimal        | Si        | >= 0                |
| supplierSku      | string \| null | No        | max: 64 caracteres  |
| minOrderQuantity | int            | No        | >= 1. Default: 1    |
| leadTimeDays     | int \| null    | No        | >= 0                |
| isPreferred      | bool           | No        | Default: false      |

> **Nota:** `supplierId` se toma del path param, no del body. El campo `supplierId` del body se ignora en este endpoint.

**Response: `200`**

```json
{
  "data": {
    "id": 1,
    "supplierId": 5,
    "productId": 10,
    "purchasePrice": 25.50,
    "supplierSku": "ABC-001",
    "minOrderQuantity": 5,
    "leadTimeDays": 3,
    "isPreferred": true
  },
  "meta": {
    "requestId": "uuid-string",
    "timestamp": "2026-03-07T12:00:00.000Z"
  }
}
```

**Error: `400`** - Si ya existe la combinacion (supplierId, productId) (constraint unico en BD)

---

### 3.2 Listar productos de un proveedor

```
GET /suppliers/{supplier_id}/products
```

**Path Params:** `supplier_id` (int) - ID del proveedor

**Response: `200`** - `ListResponse[SupplierProductResponse]`

---

### 3.3 Obtener producto-proveedor por ID

```
GET /supplier-products/{id}
```

**Path Params:** `id` (int) - ID del registro supplier_product

**Response: `200`** - `DataResponse[SupplierProductResponse]`

**Error: `404`** - No encontrado

---

### 3.4 Actualizar producto-proveedor

```
PUT /supplier-products/{id}
```

**Path Params:** `id` (int) - ID del registro supplier_product

**Request Body:** Schema completo de SupplierProductRequest (incluye supplierId y productId)

**Response: `200`** - `DataResponse[SupplierProductResponse]`

---

### 3.5 Eliminar producto-proveedor

```
DELETE /supplier-products/{id}
```

**Path Params:** `id` (int) - ID del registro

**Response: `204`** - Sin contenido

---

### 3.6 Obtener proveedores de un producto

```
GET /supplier-products/by-product/{product_id}
```

**Path Params:** `product_id` (int) - ID del producto del catalogo

**Response: `200`** - `ListResponse[SupplierProductResponse]` (todos los proveedores que ofrecen ese producto)

---

## 4. Manejo de Errores

Todas las respuestas de error siguen este formato:

```json
{
  "errors": [
    {
      "code": "NOT_FOUND",
      "message": "Supplier with id 999 not found",
      "field": null
    }
  ],
  "meta": {
    "requestId": "uuid-string",
    "timestamp": "2026-03-07T12:00:00.000Z"
  }
}
```

### Codigos de error HTTP

| Codigo | Cuando                                                         |
| ------ | -------------------------------------------------------------- |
| 400    | Violacion de regla de negocio (DomainError, ApplicationError)  |
| 404    | Recurso no encontrado (NotFoundError)                          |
| 422    | Validacion de campos fallida (ValidationError de Pydantic)     |
| 500    | Error interno del servidor                                     |

### Errores comunes por endpoint

| Endpoint                          | Posibles errores                                        |
| --------------------------------- | ------------------------------------------------------- |
| POST /suppliers                   | 422 (campos invalidos), 400 (email/taxId invalidos)     |
| GET /suppliers/{id}               | 404 (proveedor no existe)                               |
| PUT /suppliers/{id}               | 404, 422, 400                                           |
| DELETE /suppliers/{id}            | 404                                                     |
| POST /suppliers/{id}/activate     | 404                                                     |
| POST /suppliers/{id}/deactivate   | 404                                                     |
| POST /suppliers/{sid}/contacts    | 422                                                     |
| GET /supplier-contacts/{id}       | 404                                                     |
| POST /suppliers/{sid}/products    | 422, 400 (duplicado supplier+product)                   |
| GET /supplier-products/{id}       | 404                                                     |

---

## 5. Enums

### TaxType

| Valor | Nombre       | Descripcion               |
| ----- | ------------ | ------------------------- |
| 1     | RUC          | Registro Unico de Contribuyente |
| 2     | NATIONAL_ID  | Cedula de identidad       |
| 3     | PASSPORT     | Pasaporte                 |
| 4     | FOREIGN_ID   | Identificacion extranjera |

---

## 6. Resumen de Endpoints

| Metodo | Ruta                                      | Descripcion                         |
| ------ | ----------------------------------------- | ----------------------------------- |
| POST   | /suppliers                                | Crear proveedor                     |
| GET    | /suppliers                                | Listar proveedores (paginado)       |
| GET    | /suppliers/{id}                           | Obtener proveedor por ID            |
| PUT    | /suppliers/{id}                           | Actualizar proveedor                |
| DELETE | /suppliers/{id}                           | Eliminar proveedor                  |
| POST   | /suppliers/{id}/activate                  | Activar proveedor                   |
| POST   | /suppliers/{id}/deactivate                | Desactivar proveedor                |
| POST   | /suppliers/{supplier_id}/contacts         | Crear contacto                      |
| GET    | /suppliers/{supplier_id}/contacts         | Listar contactos del proveedor      |
| GET    | /supplier-contacts/{id}                   | Obtener contacto por ID             |
| PUT    | /supplier-contacts/{id}                   | Actualizar contacto                 |
| DELETE | /supplier-contacts/{id}                   | Eliminar contacto                   |
| POST   | /suppliers/{supplier_id}/products         | Agregar producto al proveedor       |
| GET    | /suppliers/{supplier_id}/products         | Listar productos del proveedor      |
| GET    | /supplier-products/{id}                   | Obtener producto-proveedor por ID   |
| PUT    | /supplier-products/{id}                   | Actualizar producto-proveedor       |
| DELETE | /supplier-products/{id}                   | Eliminar producto-proveedor         |
| GET    | /supplier-products/by-product/{product_id}| Proveedores de un producto          |

---

## 7. Tipos TypeScript (referencia para frontend)

```typescript
// Enums
enum TaxType {
  RUC = 1,
  NATIONAL_ID = 2,
  PASSPORT = 3,
  FOREIGN_ID = 4,
}

// Supplier
interface Supplier {
  id: number;
  name: string;
  taxId: string;
  taxType: TaxType;
  email: string | null;
  phone: string | null;
  address: string | null;
  city: string | null;
  country: string | null;
  paymentTerms: number | null;
  leadTimeDays: number | null;
  isActive: boolean;
  notes: string | null;
}

interface SupplierForm {
  name: string;               // required, 1-128 chars
  taxId: string;              // required, 1-32 chars
  taxType?: TaxType;          // default: 1
  email?: string | null;      // max 128
  phone?: string | null;      // max 32
  address?: string | null;    // max 255
  city?: string | null;       // max 64
  country?: string | null;    // max 64
  paymentTerms?: number | null; // >= 0
  leadTimeDays?: number | null; // >= 0
  isActive?: boolean;         // default: true
  notes?: string | null;      // max 512
}

// Supplier Contact
interface SupplierContact {
  id: number;
  supplierId: number;
  name: string;
  role: string | null;
  email: string | null;
  phone: string | null;
}

interface SupplierContactForm {
  name: string;               // required, 1-128 chars
  role?: string | null;       // max 64
  email?: string | null;      // max 128
  phone?: string | null;      // max 32
}

// Supplier Product
interface SupplierProduct {
  id: number;
  supplierId: number;
  productId: number;
  productName?: string | null; // solo en GET /suppliers/{id}/products
  productSku?: string | null;
  purchasePrice: number;
  supplierSku: string | null;
  minOrderQuantity: number;
  leadTimeDays: number | null;
  isPreferred: boolean;
}

interface SupplierProductForm {
  productId: number;          // required, >= 1
  purchasePrice: number;      // required, >= 0
  supplierSku?: string | null; // max 64
  minOrderQuantity?: number;  // >= 1, default: 1
  leadTimeDays?: number | null; // >= 0
  isPreferred?: boolean;      // default: false
}

// Response wrappers
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

interface ErrorDetail {
  code: string;
  message: string;
  field: string | null;
}

interface ErrorResponse {
  errors: ErrorDetail[];
  meta: Meta;
}
```
