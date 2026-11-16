# Imports Module — API Specification (S5.8)

Importación masiva de datos iniciales: productos, presentaciones, precios de las listas, clientes,
proveedores y saldos iniciales de inventario, desde CSV o XLSX. Un archivo se sube y se valida fila
por fila **sin escribir nada del negocio**. Una vez confirmado, el worker lo importa por lotes con los
comandos de cada módulo, a nombre de quien lo subió. Cada fila se identifica por su clave natural
(SKU, identificación, código), así que volver a importar el mismo archivo no duplica nada.

Todas las rutas piden `import:write`, que solo tiene el rol ADMIN. La guía para usuarios está en
[imports-guide.md](imports-guide.md).

## 1. Conceptos y enums

### ImportKind

Cada tipo tiene su plantilla. Se cargan en este orden, porque cada uno valida contra lo que ya está
en la base: los productos antes que sus presentaciones, precios y saldos.

| Valor | Clave natural | Comandos que usa |
|---|---|---|
| `PRODUCTS` | `sku` | `CreateProductCommand`, `UpdateProductCommand`, `CreateCategoryCommand` |
| `PRESENTATIONS` | `sku` + `presentacion` | `Create/UpdateProductPresentationCommand` |
| `PRICES` | `lista` + `sku` + `presentacion` + `cantidad_minima` | `Create/UpdatePriceListItemCommand` |
| `CUSTOMERS` | `identificacion` | `Create/UpdateCustomerCommand`, `ChangeCustomerPriceListCommand` |
| `SUPPLIERS` | `identificacion` | `Create/UpdateSupplierCommand` |
| `STOCK` | `bodega` + `ubicacion` + `sku` | `CreateAdjustmentCommand`, `AddAdjustmentItemCommand`, `ConfirmAdjustmentCommand` |

Las columnas de cada plantilla, con su descripción y ejemplo, salen de `GET /templates` (las define
`src/imports/app/kinds/*.py`). Los encabezados se comparan sin tildes, mayúsculas ni espacios
(`Precio venta` = `precio_venta`). Una columna que la plantilla no tiene rechaza el archivo.

### ImportMode

- `SKIP`: crea los registros nuevos y salta las filas de los que existen. El encabezado debe traer
  todas las columnas obligatorias.
- `UPDATE`: crea los nuevos y actualiza los que existen con las **celdas llenas** de la fila; una
  celda vacía conserva el valor actual. Basta con las columnas clave (un archivo `sku,precio_venta`
  actualiza precios). Un registro cuyos valores no cambian queda `UNCHANGED` y no se escribe.

En `STOCK` la cantidad es la que debe quedar en la ubicación: el ajuste lleva el stock a ella. Con
`SKIP` se saltan las ubicaciones que ya tienen stock; con la misma cantidad, la fila queda `UNCHANGED`.

### ImportStatus

| Valor | Significado |
|---|---|
| `VALIDATED` | Todas las filas son válidas; espera la confirmación |
| `INVALID` | Alguna fila tiene errores: no se puede confirmar |
| `QUEUED` | Confirmada; el worker la toma en segundos |
| `RUNNING` | El worker la está importando |
| `COMPLETED` | Terminó |
| `FAILED` | Una fila falló al ejecutarse (o venció sin confirmarse): `failedRow` y `failure` dicen por qué |

### ImportRowAction

`CREATE`, `UPDATE`, `UNCHANGED`, `SKIP`, `ERROR`: lo que haría la fila al validar el archivo y, una
vez ejecutada, lo que hizo.

## 2. Cómo se valida y cómo se ejecuta

### 2.1 Carga y validación (`POST /imports`)

1. El archivo se lee en streaming: CSV en UTF-8 (con o sin BOM) o Windows-1252, separado por coma,
   punto y coma o tabulador (se detecta en el encabezado), o la primera hoja de un XLSX
   (openpyxl en modo `read_only`). Los `.xls` no se admiten.
2. Límites: `IMPORT_MAX_FILE_BYTES` (10 MiB; el middleware de tamaño acepta ese cuerpo solo en esta
   ruta) e `IMPORT_MAX_ROWS` (50.000 filas). Las filas vacías no cuentan.
3. Cada fila se valida contra los datos de la empresa, con pocas consultas por archivo
   (`ImportLookups`): unidades, categorías, productos, presentaciones y códigos de barras, listas y
   sus precios, clientes y proveedores, bodegas, ubicaciones y stock. Se reutilizan las reglas del
   dominio: cédula y RUC (`TaxId`), correo, IVA 5 para materiales de construcción, decimales de la
   unidad (y de la presentación, `presentation_decimals`), factor mayor que cero, la lista general
   solo con escalas. Se marcan los duplicados dentro del archivo.
4. Las filas se guardan en `import_job_rows` (los valores tal como venían, la acción y los errores)
   y el trabajo queda `VALIDATED` o `INVALID`. Nada del negocio se escribe.

Errores de una fila (`errors[].code`): `REQUIRED`, `INVALID_VALUE`, `DUPLICATE_IN_FILE`, `NOT_FOUND`,
`ALREADY_IN_USE` (código de barras de otro producto) y `NOT_ALLOWED` (la presentación base, un
servicio con stock, la lista general sin cantidad mínima, un material sin IVA 5). Los mensajes están
en español, para quien corrige el archivo.

### 2.2 Ejecución (worker)

- `POST /{id}/confirm` deja la importación `QUEUED` y queda en la bitácora (`import.confirmed`).
- La tarea `imports` del worker (cada `IMPORT_POLL_INTERVAL_SECONDS`, 2 s) busca como faclab_worker la
  importación en cola o en curso más antigua y corre lotes de `IMPORT_BATCH_SIZE` filas (200) hasta
  agotar `IMPORT_TICK_SECONDS` (20 s).
- Cada lote es una transacción en la empresa de la importación, con el `TenantContext` de quien la
  subió (usuario, nombre, sucursal) y el `request_id` de la confirmación: la bitácora de cada comando
  lo nombra (`source=task`). El lote:
  1. bloquea el trabajo con `FOR UPDATE SKIP LOCKED` (otro worker lo salta);
  2. vuelve a planificar sus filas con los datos de ahora;
  3. las ejecuta con los comandos de su módulo;
  4. guarda la acción y el registro de cada fila (`recordId`) y avanza el cursor.
- Si el worker muere a mitad de un lote, el lote se revierte y el siguiente tick lo retoma desde el
  cursor.
- Una fila que falla (los datos cambiaron desde la validación o un comando la rechazó) revierte su
  lote y deja la importación `FAILED` con la fila y el mensaje. Los lotes anteriores quedan: volver a
  subir el archivo corregido no duplica lo ya importado.
- Saldos iniciales: un ajuste por bodega y por lote, con motivo `initial_balance`, la nota
  `Importación #<id>` y `adjusted_by` = el usuario, confirmado en el mismo lote (`adjustment.confirmed`).
  Lo que agrega entra al `costo_unitario` de la fila y fija el costo promedio de la ubicación (S5.6);
  sin costo, al promedio que tenga o al precio de compra del producto. Lo que quita sale al promedio.
- Las filas de las importaciones terminadas (y de las validadas que nunca se confirmaron, que pasan a
  `FAILED`) se borran `IMPORT_RETENTION_DAYS` (30) después; el trabajo queda con sus conteos.

## 3. Endpoints (Admin)

Todos bajo `/api/admin/imports`, con `import:write`.

| Método y ruta | Qué hace |
|---|---|
| `GET /templates` | Las plantillas y sus columnas (`name`, `description`, `example`, `key`, `required`) |
| `GET /templates/{kind}?format=xlsx\|csv` | La plantilla: XLSX (por defecto, celdas de texto y una hoja "Instrucciones") o CSV con BOM |
| `POST /` | Multipart: `kind`, `mode` (`SKIP` por defecto) y `file`. 201 con la importación `VALIDATED` o `INVALID` |
| `GET /?kind=&status=` | Las importaciones, la última primero, paginadas |
| `GET /{id}` | Una importación y su avance (`processedRows` de `totalRows`) |
| `GET /{id}/rows?action=ERROR` | Sus filas en orden, paginadas; con `action`, solo esas |
| `GET /{id}/errors?format=xlsx\|csv` | Reporte de errores: una línea por error (`fila`, `columna`, `codigo`, `mensaje`) más las celdas de la fila; la fila que detuvo una importación `FAILED` va al final |
| `POST /{id}/confirm` | La deja en cola. 409 `IMPORT_NOT_CONFIRMABLE` si no está `VALIDATED` |

## 4. Formato de respuestas

### ImportJob

```json
{
  "id": 12,
  "kind": "PRODUCTS",
  "mode": "UPDATE",
  "status": "RUNNING",
  "fileName": "productos.xlsx",
  "fileSize": 724112,
  "totalRows": 10000,
  "processedRows": 4200,
  "planned": {"create": 9800, "update": 150, "unchanged": 50, "skip": 0, "error": 0},
  "done": {"create": 4100, "update": 80, "unchanged": 20, "skip": 0, "error": 0},
  "userName": "Ana Pérez",
  "failedRow": null,
  "failure": null,
  "createdAt": "2026-11-16T10:00:00",
  "confirmedAt": "2026-11-16T10:01:00",
  "startedAt": "2026-11-16T10:01:02",
  "finishedAt": null
}
```

### ImportRow

```json
{
  "id": 88,
  "rowNumber": 5,
  "action": "ERROR",
  "errors": [{"column": "unidad", "code": "NOT_FOUND", "message": "No existe la unidad kg"}],
  "data": {"sku": "PAL-1", "nombre": "Pala", "unidad": "kg", "precio_venta": "9.50"},
  "recordId": null
}
```

`rowNumber` es la línea en la hoja (el encabezado es la 1). `data` lleva las celdas por encabezado de
la plantilla, tal como venían.

## 5. Errores

| Código | HTTP | Cuándo |
|---|---|---|
| `IMPORT_FILE_INVALID` | 422 | El archivo no se puede leer como su plantilla: vacío, `.xls`, Excel dañado, CSV mal formado, columnas que la plantilla no tiene o repetidas, faltan columnas obligatorias, más de `IMPORT_MAX_ROWS` filas o de `IMPORT_MAX_FILE_BYTES` |
| `REQUEST_TOO_LARGE` | 413 | El cuerpo pasa de `IMPORT_MAX_FILE_BYTES` + 64 KiB |
| `IMPORT_NOT_CONFIRMABLE` | 409 | Se confirma una importación que no está `VALIDATED` |
| `NOT_FOUND` | 404 | La importación no existe o es de otra empresa |
| `PERMISSION_DENIED` | 403 | Sin `import:write` |

## 6. Fuera de alcance (pendiente)

Ver la ficha [S5.8](architecture/sessions/S5.8-importacion-masiva.md), sección "Lo que quedó fuera".
