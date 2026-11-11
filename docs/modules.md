# Modulos de Dominio

## Organizacion

Estructura de la empresa (`src/organization/`, S2.5): sucursales, puntos de emision y
terminales del POS. Rutas en `/api/admin/branches`, `/api/admin/emission-points` y
`/api/admin/pos-terminals` (`organization:read`; escribir es `organization:write`, solo
ADMIN). La CLI de alta (`make provision-tenant`) crea la estructura minima: matriz 001,
punto de emision 001, bodega `BOD-001` con su ubicacion `GENERAL`, la terminal `CAJA-01` y la lista
de precios general (S5.3).

### Branch

Una sucursal: un establecimiento del SRI.

**Campos:** `id`, `establishment_code` (tres digitos, `001` a `999`, unico por empresa), `name`,
`address`, `is_main` (la matriz; una por empresa, la crea el alta y no se borra), `is_active`,
`price_list_id` (S5.3: la lista de precios de sus ventas cuando el cliente no tiene una; se cambia
con el `PUT` de la sucursal y queda en `branch.updated`)

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
`doc_type` (`SALE`, `REFUND`, `QUOTE` desde S5.4; `PURCHASE_ORDER` es de la empresa, con
`branch_id` nulo) y `last_value`, el ultimo numero emitido. `DocumentNumbering` lo incrementa con un
upsert dentro de la transaccion del documento y lo formatea con el codigo de establecimiento de la
sucursal: `V-001-000123`, `D-001-000045`, `COT-001-000012`.

---

## Catalogo

### Product

Gestion del catalogo de productos con categorias.

**Entidades:** `Category`, `Product`, `ProductPresentation`

**Campos clave de Product:**
- `id`, `sku`, `name`, `description`
- `category_id`, `unit_of_measure_id` (obligatoria desde S5.2: la unidad base, en la que se lleva el stock)
- `sale_price`, `purchase_price`: por unidad base
- `barcode` (en la API): el de la unidad, guardado en su presentacion base
- `tax_code`: IVA del producto; cada linea de venta lo copia al agregarse
- `construction_material_code` (opcional): subcategoria de material de construccion
- `is_active`, `is_service`, `min_stock`, `max_stock`, `reorder_point`, `lead_time_days`, `created_at`

**Materiales de construccion (S4.6):** los materiales de la Res. NAC-DGERCGC24-00000013 llevan su codigo de la Tabla 31 del Anexo 23 de la ficha tecnica offline (version 2.34). `constructionMaterialCode` es opcional y solo acepta los 18 codigos de `ConstructionMaterialCode`. Con un codigo, el producto debe tener la tarifa de `CONSTRUCTION_MATERIAL_TAX_CODE` (IVA 5%, en `src/shared/domain/tax.py`); otra tarifa responde 400 `CONSTRUCTION_MATERIAL_TAX_MISMATCH`, al crear y al editar. Un producto con IVA 5% sin codigo sigue permitido. Como un PUT reemplaza el producto, enviarlo sin el codigo lo borra. El codigo viaja en `sales.confirmed` y `credit_notes.requested`, y faclab-invoicing lo escribe en `codigoAuxiliar` de la factura y en `codigoAdicional` de la nota de credito, en lugar del SKU. Los productos existentes no se reclasifican: cada empresa elige el codigo y la tarifa de sus materiales.

**Presentaciones (S5.2):** una ferreteria compra por caja o rollo y vende por unidad o metro. Cada
producto tiene presentaciones (`product_presentations`, `ProductPresentation`):

- La **base** (`is_base`), una por producto: su unidad de medida, con factor 1, el nombre de la unidad,
  el codigo de barras del producto y sus precios (no tiene precios propios). La crean y la mantienen los
  comandos de producto: si cambia la unidad, se renombra; `barcode` de la API del producto lee y escribe
  el suyo. No se desactiva ni se borra, y de ella solo cambia el codigo de barras (si no, 400
  `BASE_PRESENTATION_FIXED`).
- Las demas (caja de 100, rollo de 50 m): `factor` decimal (cuantas unidades base trae, mayor que cero:
  422 desde el validador y `ck_product_presentations_factor_positive` en la base), `barcode`,
  `sale_price` y `purchase_price` opcionales (sin ellos, factor x los del producto: `effectiveSalePrice`
  y `effectivePurchasePrice` en las respuestas) e `is_active`. El factor debe caber en los decimales de
  la unidad (una unidad entera no tiene cajas de 2,5).
- El codigo de barras es unico en la empresa entre todas las presentaciones
  (`uq_product_presentations_tenant_barcode`, 409 `PRODUCT_BARCODE_ALREADY_EXISTS`); el nombre, unico en
  su producto (409 `PRODUCT_PRESENTATION_ALREADY_EXISTS`).
- Una cantidad en una presentacion admite los decimales de la unidad menos los del factor
  (`presentation_decimals`): caja de 100 en una unidad entera, 0; rollo de 50 m en metros, 2. Asi su
  equivalente en unidades base siempre cabe en la unidad (`ProductQuantities.ensure_for_presentation` y
  `ensure_in_presentations`, 422 `QUANTITY_PRECISION_EXCEEDED`). Cada presentacion de las respuestas
  lleva su `quantityDecimals`.
- Las lineas de venta, devolucion y compra guardan su `presentation_id`, una copia de su factor
  (`unit_factor`) y, las que mueven stock, `base_quantity` = cantidad x factor. Cantidad y precio son de
  la presentacion; el stock, los movimientos, los lotes y las cantidades de los reportes van en unidades
  base. Una presentacion que alguna linea usa no se borra (409 `RECORD_IN_USE`): se desactiva, y una
  inactiva no se vende ni se compra (400 `PRESENTATION_INACTIVE`).
- Rutas: `GET`/`POST /api/admin/products/{id}/presentations`, `PUT`/`DELETE
  /api/admin/products/{id}/presentations/{presentation_id}` (`product:read`/`product:write`), auditadas
  como `product.presentation_created`/`updated`/`deleted` (recurso: el producto). Las respuestas de
  producto listan sus presentaciones (la base primero, luego por factor). La busqueda (`search`, `term`)
  encuentra un producto por el codigo de barras de cualquiera de sus presentaciones activas, y `GET
  /api/pos/products/barcode?code=` responde el producto y la presentacion de un codigo escaneado.

**Comandos:** `CreateCategory`, `UpdateCategory`, `DeleteCategory`, `CreateProduct`, `UpdateProduct`, `DeleteProduct`, `CreateProductPresentation`, `UpdateProductPresentation`, `DeleteProductPresentation`

**Queries:** `GetAllCategories`, `GetCategoryById`, `GetAllProducts`, `GetProductById`, `SearchProducts`, `GetProductByBarcode`, `GetProductPresentations`

**Eventos:** `ProductCreated`, `ProductUpdated`

---

### UoM (Unidades de Medida)

Registro de unidades de medida vinculadas a productos.

**Entidades:** `UnitOfMeasure`

**Campos:** `id`, `name`, `symbol`, `description`, `is_active`, `decimals`

**Decimales (S5.1):** `decimals` (0 a 6, 0 por defecto) dice cuántos decimales admite una cantidad en
esa unidad: 0 para unidades enteras, 2 para metros, 3 para kilos. Las cantidades se guardan como
`numeric(18, 6)` (lo que admite `cantidad` en el XML 1.1.0 del SRI) y la API las envía como número
JSON. Cada comando que recibe una cantidad escrita por el usuario la valida con `ProductQuantities`
(`src/catalog/product/app/quantities.py`) contra la unidad de su producto; un producto sin unidad solo
acepta enteros, y una cantidad con más decimales responde 422 `QUANTITY_PRECISION_EXCEEDED`. Los
movimientos que crean los documentos no se validan otra vez. Las respuestas de producto llevan
`unitSymbol` y `quantityDecimals`. Desde S5.2 todo producto tiene unidad: la migracion
`e3b7a91c5d20` dio a los que no tenian la unidad `und` ("Unidad", 0 decimales) de su empresa.

**Comandos:** `CreateUnitOfMeasure`, `UpdateUnitOfMeasure`, `DeleteUnitOfMeasure`

**Queries:** `GetAllUnitsOfMeasure`, `GetUnitOfMeasureById`

---

## Listas de precios

Listas de precios de la empresa (`src/pricing/`, S5.3, F-06): minorista, mayorista, por volumen.
Rutas en `/api/admin/price-lists` (`product:read`; escribir es `product:write`: quien cambia el precio
de un producto cambia sus listas).

**Entidades:** `PriceList`, `PriceListItem`

**Campos PriceList:** `id`, `name` (unico por empresa), `description`, `is_default` (la general, una
por empresa), `is_active`, `valid_from` y `valid_to` (vigencia, fechas inclusivas, opcionales)

**Campos PriceListItem:** `id`, `price_list_id`, `product_id`, `presentation_id` (sin ella al crear: la
unidad base), `min_quantity` (desde que cantidad rige, en su presentacion: 0 es el precio base de la
lista, mas es una escala por volumen; con los decimales de la presentacion), `price` (de una unidad de
su presentacion). Un solo precio por presentacion y cantidad minima
(`PRICE_LIST_ITEM_ALREADY_EXISTS`, 409).

**Lista general:** la crean la migracion `924daed89837` y el alta de empresa. Su precio base es el del
producto y sus presentaciones (`sale_price`, que se sigue editando en el producto): solo guarda escalas
para todos (`min_quantity` 0 responde 400 `DEFAULT_PRICE_LIST_BASE_PRICE`). Siempre esta activa, sin
vigencia, y no se borra (`DEFAULT_PRICE_LIST_LOCKED`).

**Asignacion:** un cliente compra con su lista (`customers.price_list_id`, `PUT
/api/admin/customers/{id}/price-list`, `product:write`: un cajero edita clientes pero no sus precios;
auditado como `customer.price_list_changed`) y una sucursal tiene la suya para los clientes sin lista
(`branches.price_list_id`). Una lista asignada no se borra (`RECORD_IN_USE`, 409): se desactiva o se
quita la asignacion. Borrar una lista borra sus precios.

**Resolucion del precio** (`PriceResolver`, `src/pricing/app/resolver.py`; regla pura en
`src/pricing/domain/services.py`): la cadena de una venta es la lista del cliente, la de su sucursal y
la general, saltando las inactivas o fuera de vigencia. La primera lista con un precio para la linea
gana; sin ninguno, la linea toma el de su presentacion (el propio o factor x el del producto). Dentro
de una lista, una presentacion vendida en cantidad q toma el item de esa presentacion con la mayor
cantidad minima que no supere q; si la lista no tiene item de esa presentacion, el de la unidad base
con la mayor cantidad minima que no supere q x factor, multiplicado por el factor (2 cajas de 25 son
50 unidades). El POS la usa al agregar un item, al cambiar su cantidad (una linea sin override vuelve a
tomar su precio, asi alcanza la escala) y en la venta rapida; `POST /api/pos/prices/resolve` la expone
para el carrito (ver `docs/pos-api-spec.md`). Un precio distinto del resuelto es un override: exige
motivo y queda en la bitacora (`sale.price_overridden`).

**Comandos:** `CreatePriceList`, `UpdatePriceList`, `DeletePriceList`, `CreatePriceListItem`,
`UpdatePriceListItem` (precio y cantidad minima; el producto y la presentacion no cambian),
`DeletePriceListItem`, todos auditados (`price_list.created/updated/deleted`,
`price_list.item_created/updated/deleted`, con la lista como recurso)

**Queries:** `GetPriceLists` (la general primero, luego por nombre; filtro `isActive`),
`GetPriceList`, `GetPriceListItems` (filtro `productId`; con el nombre y el SKU del producto y el
nombre y el factor de la presentacion), `ResolvePrices`

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

**Campos Customer:** `id`, `name`, `tax_id` (RUC/RUC), `tax_type`, `email`, `phone`, `address`, `is_active`, `price_list_id` (S5.3: la lista de precios con que compra; se cambia aparte con `PUT /api/admin/customers/{id}/price-list`, que pide `product:write`, y la edicion del cliente la conserva), `created_at`

**Value Objects usados:** `TaxId`, `Email`

**Ciclo de vida:** activo / inactivo (activate/deactivate)

**Comandos:** `CreateCustomer`, `UpdateCustomer`, `DeleteCustomer`, `ActivateCustomer`, `DeactivateCustomer`, `ChangeCustomerPriceList` (auditado como `customer.price_list_changed`), `CreateCustomerContact`, `UpdateCustomerContact`, `DeleteCustomerContact`

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

**Conciliacion con faclab-invoicing (S4.3, `src/invoicing/`):** la tarea `invoice_reconciliation`
del worker abre una discrepancia (`invoice_discrepancies`) por cada venta confirmada que sigue sin
resultado de facturacion 30 minutos despues de enviarse (`confirmed_without_result`), y el
consumidor de `invoices` otra cuando el SRI autoriza la factura de una venta anulada
(`authorized_on_cancelled`). `GET /api/admin/invoice-discrepancies` las lista y
`POST .../{id}/review` las marca revisadas; el reenvio (`POST /api/admin/sales/{id}/request-invoice`)
y el resultado de la factura las resuelven. Detalle en [sales-spec.md](sales-spec.md) (2.6).

**Nota de credito (S4.5, `src/invoicing/`):** una devolucion completada de una venta facturada pide su
nota (codDoc 04) en la misma transaccion, por el outbox (`credit_notes.requested`); la de una venta aun
sin autorizar, cuando se autoriza. El resultado llega por `credit_notes.results` y queda en la tabla
`credit_notes`, que muestran la devolucion y la discrepancia. Anular una venta facturada es una
devolucion total; cuando todo esta devuelto y acreditado, su factura pasa a `CREDITED` y la venta sigue
`INVOICED`. La factura a consumidor final no admite nota (Res. NAC-DGERCGC25-00000014, art. 3): esa
devolucion se rechaza. Detalle en [pos-api-spec.md](pos-api-spec.md) (3) y
[sales-spec.md](sales-spec.md) (2.6).

---

## Cotizaciones

Proformas que una sucursal entrega para una obra (`src/quotes/`, S5.4, F-07). Rutas en
`/api/admin/quotes` (`sale:read`; escribir es `sale:write`, los mismos roles que venden) y, para
cobrarlas, `/api/pos/quotes` (`pos:operate`). Spec en [quotes-spec.md](quotes-spec.md).

**Entidades:** `Quote`, `QuoteItem`

**Estados:** `DRAFT` → `SENT` → `ACCEPTED` → `CONVERTED`; las abiertas (`DRAFT`, `SENT`, `ACCEPTED`)
pasan a `EXPIRED` cuando vence su fecha, y una vencida se renueva a `DRAFT`.

**Campos Quote:** `id`, `branch_id` (la que la emite y numera), `number` (`COT-001-000012`, al crearla),
`customer_id` (nulo: consumidor final), `status`, `issue_date`, `valid_until` (ultimo dia en que rige,
hoy o despues), `subtotal`, `tax`, `total`, `notes`, `created_by` (del token), `sent_at`,
`accepted_at`, `converted_at`

**Campos QuoteItem:** `id`, `quote_id`, `product_id`, `presentation_id` (sin ella al crear: la unidad
base), `quantity` (en su presentacion, con sus decimales), `unit_factor`, `unit_price` (el de sus
listas), `discount` (% de la linea), `tax_code`, `tax_amount`

**Precios:** cada linea toma el precio que tendria hoy una venta de su cliente en su sucursal
(`PriceResolver`, S5.3); la cotizacion no lleva precios a mano (`PRODUCT_WITHOUT_PRICE` si ni las
listas ni el producto lo tienen). Cambiar la cantidad aplica la escala que corresponda; cambiar el
cliente o renovarla vuelve a cotizar todas las lineas. Los totales se calculan como los de una venta
sin descuento global, asi el total cotizado es el que cobra el POS.

**Vigencia:** una abierta con la fecha ya pasada se trata como vencida aunque la tarea
`quote_expiration` del worker (cada `WORKER_PURGE_INTERVAL_SECONDS`, como faclab_worker en todas las
empresas) todavia no la haya marcado `EXPIRED`. Una vencida no se envia, acepta ni cobra
(`QUOTE_EXPIRED`) hasta renovarla con una fecha nueva: vuelve a `DRAFT`, emitida hoy y con los
precios de hoy.

**PDF y correo:** `GET /api/admin/quotes/{id}/pdf` la dibuja con reportlab (empresa, sucursal,
cliente, items, totales por tarifa de IVA, notas; "Documento sin valor tributario"). `POST
.../{id}/email` envia ese PDF por SMTP a la direccion dada o a la del cliente
(`QUOTE_EMAIL_REQUIRED` sin ninguna) y marca `SENT` un borrador; el servidor responde dentro de la
solicitud (`EMAIL_DELIVERY_FAILED` 502, nada cambia) y con `EMAIL_ENABLED=false` responde
`EMAIL_DISABLED`.

**Conversion a venta:** se cobra en una terminal de su sucursal con la venta rapida y su `quoteId`
(`QuoteConversion`): bloquea la cotizacion antes que el stock y el contador, exige que rija, que sea
de la sucursal (`QUOTE_OUTSIDE_BRANCH`), el mismo cliente (`QUOTE_CUSTOMER_CHANGED`) y sus mismos items
(producto, presentacion, cantidad y descuento; `QUOTE_ITEMS_CHANGED`). La venta guarda `quote_id`
(una por cotizacion, `QUOTE_ALREADY_CONVERTED` 409) y la cotizacion pasa a `CONVERTED`. El stock se
valida al descontarlo (`INSUFFICIENT_STOCK`): la cotizacion no lo reserva. Si un precio cambio desde
que se cotizo, el cajero elige en el POS entre el cotizado (un override con el motivo
`Cotizacion <numero>`, auditado en `sale.price_overridden`) y el actual.

**Comandos:** `CreateQuote`, `UpdateQuote` (solo borrador), `DeleteQuote` (solo borrador; su numero no
se reutiliza), `AddQuoteItem`, `UpdateQuoteItem`, `RemoveQuoteItem`, `SendQuote`, `AcceptQuote`,
`RenewQuote`, `EmailQuote`. Ninguno se audita: una cotizacion no mueve dinero ni stock.

**Queries:** `GetQuotes` (filtros `status`, `customerId`, `branchId`, `number`; solo las sucursales
del usuario), `GetQuote` (con items y la venta en que se convirtio), `GetQuotePdf`, `GetPosQuotes`
(las vigentes de la sucursal del POS, busqueda por numero o cliente) y `GetPosQuote` (precio de hoy y
stock en la ubicacion de la terminal de cada linea).

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
| Producto | `product.created`, `product.updated`, `product.price_changed` (cambio de costo, precio de venta o IVA), `product.deleted` | sku, nombre, costo, precio, IVA, codigo de material de construccion, activo; en una edicion, solo los que cambiaron (un PUT sin cambios no deja entrada) |
| Movimiento | `movement.created` (solo el manual de `POST /movements`) | producto, ubicacion, tipo, cantidad, motivo |
| Ajuste | `adjustment.confirmed`, `adjustment.cancelled` | estado, bodega, motivo, items con diferencia |
| Transferencia | `transfer.confirmed`, `transfer.received`, `transfer.cancelled` | estado, origen, destino, items |
| Lista de precios (S5.3) | `price_list.created`, `price_list.updated`, `price_list.deleted`, `price_list.item_created`, `price_list.item_updated`, `price_list.item_deleted` (con la lista como recurso), `customer.price_list_changed` | nombre, descripcion, activa, vigencia / item, producto, presentacion, cantidad minima, precio / lista del cliente antes y despues |
| Venta (POS) | `sale.cancelled`, `sale.price_overridden` (endpoint de precio y cada linea agregada a otro precio que el de su lista, en un item o en la venta rapida), `sale.discount_applied` (endpoint y venta rapida con descuento) | estado y total / precio de lista o anterior, nuevo y motivo / descuento |
| Venta (facturacion, S4.3) | `sale.invoice_requested` (reenvio a facturacion), `invoice_discrepancy.reviewed` (discrepancia de conciliacion marcada revisada) | estado, factura y motivo del rechazo antes y despues / estado, tipo, venta y nota |
| Devolucion | `refund.processed` (quien la aprueba), `refund.cancelled` | estado, numero, venta original, total, pagos |
| Caja | `cash_movement.registered`, `shift.opened`, `shift.closed` | turno, tipo, monto, motivo / fondo inicial / contado, esperado, diferencia |
| Usuario | `user.created`, `user.role_changed`, `user.branches_changed`, `user.renamed`, `user.activated`, `user.deactivated`, `user.password_reset` | usuario, rol, sucursales, nombre, activo; el restablecimiento de contrasena sin valores |
| Organizacion | `branch.*`, `emission_point.*`, `pos_terminal.*` (`created`, `updated`, `deleted`) | codigo, nombre, direccion, activo, punto de emision, ubicacion de venta |

**Regla:** toda accion sensible nueva se audita con `AuditTrail.record` y suma su escenario en
`tests/integration/postgres/test_audit_log.py`, que falla si una accion del catalogo no lo tiene.
