# Modulos de Dominio

## Organizacion

Estructura de la empresa (`src/organization/`, S2.5): sucursales, puntos de emision y
terminales del POS. Rutas en `/api/admin/branches`, `/api/admin/emission-points` y
`/api/admin/pos-terminals` (`organization:read`; escribir es `organization:write`, solo
ADMIN). La CLI de alta (`make provision-tenant`) crea la estructura minima: matriz 001,
punto de emision 001, bodega `BOD-001` con su ubicacion `GENERAL` y la terminal `CAJA-01`.

### Branch

Una sucursal: un establecimiento del SRI.

**Campos:** `id`, `establishment_code` (tres digitos, `001` a `999`, unico por empresa), `name`,
`address`, `is_main` (la matriz; una por empresa, la crea el alta y no se borra), `is_active`

**Comandos:** `CreateBranch`, `UpdateBranch`, `DeleteBranch` (no borra la matriz ni una sucursal
con bodegas, puntos de emision, terminales o accesos: `RECORD_IN_USE`)

**Queries:** `GetAllBranches`, `GetBranchById`, `GetAccessibleBranches` (las activas a las que
entra el usuario, para `/api/auth/me`)

### EmissionPoint

Un punto de emision del SRI de una sucursal.

**Campos:** `id`, `branch_id` (fijo desde que se crea), `code` (tres digitos, unico por
sucursal), `name`, `is_active`

**Comandos:** `CreateEmissionPoint`, `UpdateEmissionPoint`, `DeleteEmissionPoint`

**Queries:** `GetAllEmissionPoints` (por sucursal), `GetEmissionPointById`

### PosTerminal

Una caja del POS. Emite por un punto de emision de su sucursal y descuenta stock de una
ubicacion de una bodega de esa sucursal (`EMISSION_POINT_OUTSIDE_BRANCH`,
`LOCATION_OUTSIDE_BRANCH`). Desde S2.6 cada terminal tiene como maximo un turno abierto
(indice unico parcial), sus ventas y devoluciones mueven el stock de su ubicacion por defecto y se
numeran por sucursal (`document_sequences`, `V-001-000123` y `D-001-000045`).

**Campos:** `id`, `branch_id` (fijo desde que se crea), `emission_point_id`,
`default_location_id`, `code` (unico por sucursal), `name`, `is_active`

**Comandos:** `CreatePosTerminal`, `UpdatePosTerminal`, `DeletePosTerminal`

**Queries:** `GetAllPosTerminals` (por sucursal), `GetPosTerminalById`, `GetBranchTerminals`
(`GET /api/pos/terminals`: las activas de la sucursal de `X-Branch-Id`)

### Acceso por sucursal

`user_branch_access` (en `src/tenancy/`, sin RLS, como `memberships`) limita una membresia a
algunas sucursales; sin filas entra a todas. Se administra con
`GET`/`PUT /api/admin/users/{id}/branches` y viaja en el claim `bids` del access token. Toda
ruta autenticada que reciba `X-Branch-Id` lo valida (422 `INVALID_BRANCH_HEADER`, 403
`BRANCH_ACCESS_DENIED`) y la solicitud corre en esa sucursal (`TenantContext.branch_id`, logs y
span con `faclab.branch.id`). Las rutas de sucursal lo exigen con `require_branch`
(`BRANCH_REQUIRED`): `GET /api/pos/terminals` y, desde S2.6, las operaciones del POS
(`pos_terminal` con `X-Terminal-Id`, `pos_branch` para las de una venta, un turno o una
devolucion existentes; ver `pos-api-spec.md` §0).

### DocumentSequence

Numeracion de documentos internos por sucursal (ADR-0012, S2.6): `tenant_id`, `branch_id`,
`doc_type` (`SALE`, `REFUND`) y `last_value`, el ultimo numero emitido. `DocumentNumbering` lo
incrementa con un upsert dentro de la transaccion del documento y lo formatea con el codigo de
establecimiento de la sucursal.

---

## Catalogo

### Product

Gestion del catalogo de productos con categorias.

**Entidades:** `Category`, `Product`

**Campos clave de Product:**
- `id`, `sku`, `name`, `description`
- `category_id`, `uom_id`
- `price`, `cost`
- `is_active`, `created_at`

**Comandos:** `CreateCategory`, `UpdateCategory`, `DeleteCategory`, `CreateProduct`, `UpdateProduct`, `DeleteProduct`

**Queries:** `GetAllCategories`, `GetCategoryById`, `GetAllProducts`, `GetProductById`

**Eventos:** `ProductCreated`, `ProductUpdated`

---

### UoM (Unidades de Medida)

Registro de unidades de medida vinculadas a productos.

**Entidades:** `UnitOfMeasure`

**Campos:** `id`, `name`, `abbreviation`

**Comandos:** `CreateUnitOfMeasure`, `UpdateUnitOfMeasure`, `DeleteUnitOfMeasure`

**Queries:** `GetAllUnitsOfMeasure`, `GetUnitOfMeasureById`

---

## Inventario

### Warehouse

Instalaciones fisicas de almacenamiento.

**Entidades:** `Warehouse`

**Campos:** `id`, `branch_id` (obligatorio y fijo desde que se crea), `name`, `code`, `address`,
`is_active`, `is_default`

**Comandos:** `CreateWarehouse`, `UpdateWarehouse`, `DeleteWarehouse`

**Queries:** `GetAllWarehouses`, `GetWarehouseById`

---

### Location

Ubicaciones (estantes, zonas) dentro de un almacen.

**Entidades:** `Location`

**Campos:** `id`, `name`, `code`, `warehouse_id`, `is_active`

**Comandos:** `CreateLocation`, `UpdateLocation`, `DeleteLocation`

**Queries:** `GetAllLocations`, `GetLocationById`, `GetLocationsByWarehouse`

---

### Stock

Nivel de inventario de un producto en una ubicacion especifica. El stock no se gestiona directamente — se actualiza automaticamente mediante el evento `MovementCreated`.

**Entidades:** `Stock`

**Campos:** `id`, `product_id`, `location_id`, `quantity`, `reserved_quantity`, `min_quantity`, `updated_at`

**Queries:** `GetAllStock`, `GetStockById`, `GetStockByProduct`, `GetStockByLocation`

**Eventos recibidos:** `MovementCreated` → actualiza `quantity` (crea la fila si la ubicacion no tenia)

**Reglas (S3.2):** el stock nunca queda negativo. Una salida solo toma lo disponible
(`available_quantity = quantity - reserved_quantity`; lo reservado es de transferencias confirmadas):
un OUT que no cubre, tambien cuando la ubicacion no tiene fila, falla con `INSUFFICIENT_STOCK`. La
base lo garantiza ademas con `CHECK (quantity >= 0)` y
`CHECK (reserved_quantity >= 0 AND reserved_quantity <= quantity)`.

---

### Movement

Registro de entradas (`IN`) y salidas (`OUT`) de inventario. Cada movimiento genera el evento `MovementCreated`.

**Entidades:** `Movement`

**Campos:** `id`, `product_id`, `location_id`, `type` (IN/OUT), `quantity`, `reference`, `notes`, `created_at`

**Comandos:** `CreateMovement`

**Queries:** `GetAllMovements`, `GetMovementById`, `GetMovementsByProduct`

**Eventos publicados:** `MovementCreated`

**Origenes posibles de un Movement:**
- Confirmacion de venta → `SaleConfirmed` → OUT
- Anulacion de venta → `SaleCancelled` → IN
- Recepcion de compra → `PurchaseOrderReceived` → IN
- Ajuste de inventario → directo (la diferencia contra el stock al confirmar)
- Creacion manual → via endpoint, sin documento: `POST /api/admin/movements` no acepta
  `referenceType` ni `referenceId`, que solo llenan los flujos anteriores

---

### Lot

Trazabilidad por lote para productos perecederos o con fecha de vencimiento.

**Entidades:** `Lot`

**Campos:** `id`, `stock_id`, `lot_number`, `expiry_date`, `quantity`, `status`, `created_at`

**Comandos:** `CreateLot`, `UpdateLot`

**Queries:** `GetAllLots`, `GetLotById`, `GetLotsByStock`

**Eventos publicados:** `LotCreated`, `LotUpdated`

---

### Serial

Trazabilidad individual por numero de serie dentro de un lote.

**Entidades:** `Serial`

**Campos:** `id`, `lot_id`, `serial_number`, `status` (AVAILABLE/SOLD/RETURNED/DAMAGED), `created_at`

**Comandos:** `CreateSerial`, `UpdateSerial`

**Queries:** `GetAllSerials`, `GetSerialById`, `GetSerialsByLot`

---

### Adjustment

Ajustes de inventario para conteos fisicos, correcciones o bajas.

**Entidades:** `Adjustment`, `AdjustmentItem`

**Campos Adjustment:** `id`, `type` (COUNT/CORRECTION/WRITEOFF), `location_id`, `status`, `notes`, `created_at`

**Campos AdjustmentItem:** `id`, `adjustment_id`, `product_id`, `expected_qty`, `actual_qty`, `difference`

**Comandos:** `CreateAdjustment`, `UpdateAdjustment`, `CreateAdjustmentItem`, `UpdateAdjustmentItem`, `DeleteAdjustmentItem`

**Queries:** `GetAllAdjustments`, `GetAdjustmentById`, `GetAdjustmentItems`

---

### Transfer

Transferencias de stock entre ubicaciones.

**Entidades:** `Transfer`, `TransferItem`

**Campos Transfer:** `id`, `from_location_id`, `to_location_id`, `status`, `notes`, `created_at`

**Campos TransferItem:** `id`, `transfer_id`, `product_id`, `quantity`

**Comandos:** `CreateTransfer`, `UpdateTransfer`, `CreateTransferItem`, `UpdateTransferItem`, `DeleteTransferItem`

**Queries:** `GetAllTransfers`, `GetTransferById`, `GetTransferItems`

---

### Alert

Monitoreo de niveles de stock por debajo del minimo configurado.

**Entidades:** `Alert`

**Campos:** `id`, `stock_id`, `product_id`, `current_quantity`, `min_quantity`, `severity`, `created_at`

**Queries:** `GetAllAlerts`, `GetAlertById`, `GetAlertsByStock`, `GetAlertsByProduct`

> Las alertas se generan automaticamente cuando el stock cae por debajo del umbral minimo.

---

## Clientes

Gestion de clientes con datos fiscales, contactos y estados.

**Entidades:** `Customer`, `CustomerContact`

**Campos Customer:** `id`, `name`, `tax_id` (RUC/RUC), `tax_type`, `email`, `phone`, `address`, `is_active`, `created_at`

**Value Objects usados:** `TaxId`, `Email`

**Ciclo de vida:** activo / inactivo (activate/deactivate)

**Comandos:** `CreateCustomer`, `UpdateCustomer`, `DeleteCustomer`, `ActivateCustomer`, `DeactivateCustomer`, `CreateCustomerContact`, `UpdateCustomerContact`, `DeleteCustomerContact`

**Queries:** `GetAllCustomers`, `GetCustomerById`, `GetCustomerByTaxId`, `GetContactsByCustomer`

**Eventos:** `CustomerCreated`, `CustomerUpdated`, `CustomerActivated`, `CustomerDeactivated`

**Specifications:** `ActiveCustomers`, `CustomersByType`

---

## Proveedores

Gestion de proveedores con contactos y catalogo de productos que ofrecen.

**Entidades:** `Supplier`, `SupplierContact`, `SupplierProduct`

**Campos Supplier:** `id`, `name`, `tax_id`, `email`, `phone`, `address`, `is_active`

**Campos SupplierProduct:** `id`, `supplier_id`, `product_id`, `reference_code`, `unit_price`, `lead_time_days`

**Comandos:** `CreateSupplier`, `UpdateSupplier`, `DeleteSupplier`, `CreateSupplierContact`, `UpdateSupplierContact`, `DeleteSupplierContact`, `CreateSupplierProduct`, `UpdateSupplierProduct`, `DeleteSupplierProduct`

**Queries:** `GetAllSuppliers`, `GetSupplierById`, `GetContactsBySupplier`, `GetProductsBySupplier`

---

## Compras

Gestion de ordenes de compra y recepciones de mercaderia.

**Entidades:** `PurchaseOrder`, `PurchaseOrderItem`

**Estados de PO:** `DRAFT` → `CONFIRMED` → `RECEIVED` → `CANCELLED`

**Campos PurchaseOrder:** `id`, `supplier_id`, `status`, `notes`, `expected_date`, `created_at`

**Campos PurchaseOrderItem:** `id`, `purchase_order_id`, `product_id`, `quantity`, `unit_price`

**Comandos:** `CreatePurchaseOrder`, `AddPurchaseOrderItem`, `UpdatePurchaseOrderItem`, `DeletePurchaseOrderItem`, `ReceivePurchaseOrder`

**Queries:** `GetAllPurchaseOrders`, `GetPurchaseOrderById`, `GetPurchaseOrderItems`

**Eventos publicados:** `PurchaseOrderReceived`

**Integracion:** Al recepcionar (`ReceivePurchaseOrder`), se publica `PurchaseOrderReceived` → Inventory crea Movement(IN) por cada item → Stock se incrementa.

---

## Ventas

Ciclo de vida completo de ventas con items, pagos e integracion con inventario.

**Entidades:** `Sale`, `SaleItem`, `Payment`

**Estados:** `DRAFT` → `CONFIRMED` → `CANCELLED`

**Campos Sale:** `id`, `customer_id`, `status`, `subtotal`, `tax`, `total`, `notes`, `created_at`

**Campos SaleItem:** `id`, `sale_id`, `product_id`, `quantity`, `unit_price`, `subtotal`

**Campos Payment:** `id`, `sale_id`, `amount`, `method`, `reference`, `created_at`

**Comandos:** `CreateSale`, `AddSaleItem`, `RemoveSaleItem`, `ConfirmSale`, `CancelSale`, `RegisterPayment`

**Queries:** `GetAllSales`, `GetSaleById`, `GetSaleItems`, `GetSalePayments`

**Eventos publicados:** `SaleCreated`, `SaleConfirmed`, `SaleCancelled`

**Integracion con inventario:**
- `SaleConfirmed` → Movement(OUT) por cada item → Stock decrementado
- `SaleCancelled` → Movement(IN) por cada item → Stock restaurado

**Reglas de dominio:**
- Solo se pueden agregar items si la venta esta en estado `DRAFT`
- Solo se puede confirmar una venta `DRAFT` con al menos un item
- Solo se puede cancelar una venta `CONFIRMED` o `DRAFT`

---

## POS (Punto de Venta) — En desarrollo

> Ver [pos-plan.md](pos-plan.md) para el plan completo de desarrollo.

Operaciones atomicas del punto de venta. Confirma o anula ventas asegurando consistencia con el inventario en una sola transaccion.

**Modulo:** `src/pos/sales/`

**Comandos:** `POSConfirmSale`, `POSCancelSale`

**Diferencia con Admin:** Las operaciones POS son atomicas — verifican stock disponible y crean movimientos en la misma transaccion, evitando inconsistencias en entornos de alta concurrencia.

---

## Reportes

Consultas analiticas de inventario sin estado propio — leen datos de los modulos de inventario.

**Modulo:** `src/reports/inventory/`

**Queries disponibles:**
- `GetInventoryValuation` — valor total del inventario por producto/ubicacion
- `GetInventoryRotation` — frecuencia de rotacion por producto en un periodo
- `GetInventoryMovementsReport` — movimientos agrupados por tipo y periodo
- `GetInventorySummary` — resumen consolidado de stock, alertas y valuacion

---

## Auditoria

Bitacora inmutable de operaciones sensibles por empresa (`src/audit/`, S3.5). Ruta
`GET /api/admin/audit-log` (`audit:read`, solo ADMIN), paginada (por defecto 50, maximo 500)
y con filtros `fromDate`/`toDate` (dias completos), `actorId`, `action`, `resourceType`,
`resourceId` y `branchId`; el orden es de la mas reciente a la mas antigua. La sucursal se
filtra solo con `branchId`, no con `X-Branch-Id`.

**Entrada (`audit_log`):** `occurred_at`, actor (`actor_user_id` y `actor_name`, el nombre
completo o usuario del token en ese momento), `action` (`<recurso>.<verbo>`),
`resource_type`/`resource_id`, `branch_id` (la del recurso; si no la tiene, la de
`X-Branch-Id`), `source` (`request`, `message`, `task`), `request_id` (el `X-Request-Id`) y
`before`/`after` con solo los campos relevantes (dinero como texto decimal; nunca contrasenas,
tokens ni correos). Sin claves foraneas al recurso: la entrada sobrevive a su borrado.

**Registro:** cada handler del catalogo llama `AuditTrail.record(...)`
(`src/shared/app/audit.py`) despues de cambiar el recurso. `SqlAlchemyAuditTrail`
(`src/audit/infra/trail.py`) inserta con la sesion de la solicitud, asi que la entrada se
confirma o se revierte con la operacion. Sin contexto de empresa falla; el aprovisionamiento
del primer admin (fuera de toda empresa) no deja entrada.

**Inmutable:** RLS como toda tabla de negocio; `faclab_app` y `faclab_worker` solo tienen
`SELECT` e `INSERT` (migracion `37a810c62c07`). Ningun rol tiene `TRUNCATE`.

**Catalogo de acciones (`AuditAction`):**

| Recurso | Acciones | Campos |
|---|---|---|
| Producto | `product.created`, `product.updated`, `product.price_changed` (cambio de costo, precio de venta o IVA), `product.deleted` | sku, nombre, costo, precio, IVA, activo; en una edicion, solo los que cambiaron (un PUT sin cambios no deja entrada) |
| Movimiento | `movement.created` (solo el manual de `POST /movements`) | producto, ubicacion, tipo, cantidad, motivo |
| Ajuste | `adjustment.confirmed`, `adjustment.cancelled` | estado, bodega, motivo, items con diferencia |
| Transferencia | `transfer.confirmed`, `transfer.received`, `transfer.cancelled` | estado, origen, destino, items |
| Venta (POS) | `sale.cancelled`, `sale.price_overridden` (endpoint de precio y cada linea con otro precio en la venta rapida), `sale.discount_applied` (endpoint y venta rapida con descuento) | estado y total / precio anterior, nuevo y motivo / descuento |
| Devolucion | `refund.processed` (quien la aprueba), `refund.cancelled` | estado, numero, venta original, total, pagos |
| Caja | `cash_movement.registered`, `shift.opened`, `shift.closed` | turno, tipo, monto, motivo / fondo inicial / contado, esperado, diferencia |
| Usuario | `user.created`, `user.role_changed`, `user.branches_changed`, `user.renamed`, `user.activated`, `user.deactivated`, `user.password_reset` | usuario, rol, sucursales, nombre, activo; el restablecimiento de contrasena sin valores |
| Organizacion | `branch.*`, `emission_point.*`, `pos_terminal.*` (`created`, `updated`, `deleted`) | codigo, nombre, direccion, activo, punto de emision, ubicacion de venta |

**Regla:** toda accion sensible nueva se audita con `AuditTrail.record` y suma su escenario en
`tests/integration/postgres/test_audit_log.py`, que falla si una accion del catalogo no lo tiene.
