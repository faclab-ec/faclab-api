# Guía de importación de datos iniciales

Esta guía es para quien pone en marcha una empresa en Faclab: cómo cargar desde Excel o CSV el
catálogo, los precios, los clientes, los proveedores y el inventario con su costo. La especificación
técnica está en [imports-spec.md](imports-spec.md).

## 1. Cómo funciona

1. En **Configuración → Importar datos** se elige qué importar y se descarga su plantilla (Excel o
   CSV).
2. Se llena la plantilla: una fila por registro, con los encabezados tal como vienen.
3. Se sube el archivo. Faclab revisa **todas** las filas y muestra qué haría con cada una: crearla,
   actualizarla, dejarla igual o saltarla. **No se importa nada todavía.**
4. Si alguna fila tiene errores, se ven en la pantalla y en el reporte descargable (fila, columna y
   qué corregir). Se corrige el archivo y se vuelve a subir.
5. Con el archivo sin errores, se confirma. La importación corre en segundo plano y la pantalla
   muestra su avance; se puede salir de ella mientras tanto.

Solo un administrador puede importar. Cada registro queda a su nombre en la bitácora de auditoría.

## 2. Orden de carga

Cada plantilla busca lo que ya está en Faclab, así que se cargan en este orden y se espera a que
cada importación termine antes de subir la siguiente:

1. **Antes de importar**, desde sus pantallas: las unidades de medida (`und`, `m`, `kg`, con sus
   decimales), las bodegas y ubicaciones (la empresa nueva ya trae `BOD-001` con `GENERAL`) y las
   listas de precios distintas de la general (por ejemplo, "Mayorista").
2. **Productos.** Las categorías que no existen se crean solas.
3. **Presentaciones** (caja de 100, rollo de 50 m).
4. **Precios por lista.**
5. **Clientes** y **proveedores**.
6. **Saldos iniciales de inventario**, con su costo.

## 3. Modos

- **Solo crear los nuevos** (`SKIP`): una fila cuyo registro ya existe (mismo SKU, misma
  identificación) se salta sin tocarlo. Sirve para la carga inicial y para agregar productos nuevos.
- **Crear los nuevos y actualizar los que existen** (`UPDATE`): una fila de un registro que existe lo
  actualiza con sus **celdas llenas**. Una celda vacía conserva el valor que tiene. Así, un archivo
  con solo `sku` y `precio_venta` actualiza los precios sin tocar lo demás. Una fila con los mismos
  valores queda "sin cambios".

Repetir una importación no duplica nada: cada fila se reconoce por su clave (el SKU, la
identificación, la bodega con la ubicación y el SKU).

## 4. Formato del archivo

- **Excel (.xlsx)**, la primera hoja, o **CSV** en UTF-8 o en el "CSV" de Excel en español, separado
  por coma o punto y coma. Los `.xls` antiguos se guardan antes como `.xlsx`.
- La primera fila son los encabezados de la plantilla. Se aceptan con o sin tildes y mayúsculas
  (`Precio venta` sirve por `precio_venta`). Una columna que la plantilla no tiene rechaza el
  archivo: así un encabezado mal escrito no se ignora en silencio. Las columnas pueden ir en
  cualquier orden y las opcionales se pueden quitar.
- Las filas vacías se ignoran.
- **Números**: con punto o coma decimal (`12.50` o `12,50`), sin separador de miles. Precios y costos
  sin IVA, hasta 6 decimales. Las cantidades admiten los decimales de su unidad (una unidad de 0
  decimales, solo enteros).
- **Sí/No**: `SI`, `NO` (también `1`/`0`).
- **IVA**: `15`, `5`, `0`, `EXENTO`, `NO_OBJETO` o el código (`VAT_15`). Vacío al crear: 15 %.
- **Ceros iniciales**: la plantilla de Excel trae las celdas como texto para que Excel no quite el cero
  de una cédula (`0102030405`) ni de un código de barras. Si igual se pierde, una cédula de 9 dígitos
  o un RUC de 12 se completan con el cero.
- **Límites**: 10 MB y 50.000 filas por archivo. Un archivo más grande se divide en varios.

## 5. Plantillas

"Siempre" es una columna que identifica el registro y va en todas las filas. "Para crear" solo hace
falta cuando la fila crea el registro: al actualizar se puede dejar vacía.

### Productos

| Columna | Obligatoria | Qué lleva | Ejemplo |
|---|---|---|---|
| `sku` | Siempre | Código interno del producto, único en la empresa | TOR-0001 |
| `nombre` | Para crear | Nombre del producto | Tornillo 1/2 |
| `descripcion` | No | Descripción | — |
| `categoria` | No | Nombre de la categoría; si no existe, se crea | Tornillería |
| `unidad` | Para crear | Símbolo de la unidad base, en la que se lleva el stock (debe existir) | und |
| `codigo_barras` | No | Código de barras de la unidad base, único en la empresa | 7861234500011 |
| `precio_compra` | No | Costo por unidad base, sin IVA | 0.08 |
| `precio_venta` | Para crear | Precio de venta por unidad base, sin IVA | 0.15 |
| `iva` | No | Tarifa de IVA | 15 |
| `material_construccion` | No | Código de material de construcción del SRI (Tabla 31, p. ej. F010401 cemento); exige IVA 5 | — |
| `stock_minimo` | No | Stock mínimo, en unidad base | 10 |
| `stock_maximo` | No | Stock máximo, en unidad base | — |
| `punto_reorden` | No | Punto de reorden, en unidad base | 20 |
| `dias_reposicion` | No | Días que tarda en reponerse | — |
| `es_servicio` | No | SI si es un servicio (no lleva stock); vacía al crear, NO | NO |
| `activo` | No | NO para dejarlo inactivo; vacía al crear, SI | SI |

El código de barras de un producto es el de su unidad base. Las cajas y rollos van en la plantilla de
presentaciones.

### Presentaciones

| Columna | Obligatoria | Qué lleva | Ejemplo |
|---|---|---|---|
| `sku` | Siempre | SKU del producto (debe existir) | TOR-0001 |
| `presentacion` | Siempre | Nombre de la presentación, único en el producto | Caja x100 |
| `factor` | Para crear | Cuántas unidades base contiene | 100 |
| `codigo_barras` | No | Código de barras de la presentación, único en la empresa | 7861234500028 |
| `precio_venta` | No | Precio de la presentación sin IVA; vacía: factor × el del producto | 13.50 |
| `precio_compra` | No | Costo de la presentación sin IVA; vacía: factor × el del producto | — |
| `activo` | No | NO para dejarla inactiva | SI |

La presentación base (la unidad) se crea con el producto y no va en esta plantilla.

### Precios por lista

| Columna | Obligatoria | Qué lleva | Ejemplo |
|---|---|---|---|
| `lista` | Siempre | Nombre de la lista de precios (debe existir) | Mayorista |
| `sku` | Siempre | SKU del producto (debe existir) | TOR-0001 |
| `presentacion` | No | Nombre de la presentación; vacía: la unidad base | Caja x100 |
| `cantidad_minima` | No | Desde qué cantidad (en la presentación) aplica; vacía: 0, el precio base de la lista | 10 |
| `precio` | Para crear | Precio de la presentación sin IVA | 12.90 |

La lista **General** solo guarda escalas por volumen: su precio base es el del producto, así que en
ella `cantidad_minima` debe ser mayor que cero.

### Clientes

| Columna | Obligatoria | Qué lleva | Ejemplo |
|---|---|---|---|
| `tipo_identificacion` | Para crear | RUC, CEDULA, PASAPORTE o EXTERIOR | CEDULA |
| `identificacion` | Siempre | Cédula, RUC o pasaporte, único en la empresa | 1710034065 |
| `nombre` | Para crear | Nombre o razón social | Ferretería El Clavo |
| `email` | No | Correo electrónico | — |
| `telefono` | No | Teléfono | — |
| `direccion` | No | Dirección | — |
| `ciudad` | No | Ciudad | Quito |
| `provincia` | No | Provincia | Pichincha |
| `pais` | No | País | Ecuador |
| `cupo` | No | Cupo de crédito; vacía al crear: no compra a crédito | 500 |
| `plazo_dias` | No | Plazo de crédito en días | 30 |
| `lista_precios` | No | Lista con que compra (debe existir); vacía: la de su sucursal o la general | — |
| `activo` | No | NO para dejarlo inactivo | SI |

Una cédula o un RUC se validan como en la pantalla de clientes. El cambio de lista de precios queda en
la bitácora.

### Proveedores

| Columna | Obligatoria | Qué lleva | Ejemplo |
|---|---|---|---|
| `tipo_identificacion` | Para crear | RUC, CEDULA, PASAPORTE o EXTERIOR | RUC |
| `identificacion` | Siempre | Cédula, RUC o pasaporte, único en la empresa | 1710034065001 |
| `nombre` | Para crear | Nombre o razón social | Distribuidora Norte |
| `email` | No | Correo electrónico | — |
| `telefono` | No | Teléfono | — |
| `direccion` | No | Dirección | — |
| `ciudad` | No | Ciudad | Quito |
| `pais` | No | País | Ecuador |
| `plazo_dias` | No | Plazo de pago en días | 30 |
| `dias_entrega` | No | Días que tarda en entregar | — |
| `notas` | No | Notas | — |
| `activo` | No | NO para dejarlo inactivo | SI |

### Saldos iniciales de inventario

| Columna | Obligatoria | Qué lleva | Ejemplo |
|---|---|---|---|
| `bodega` | Siempre | Código de la bodega (debe existir) | BOD-001 |
| `ubicacion` | Siempre | Código de la ubicación dentro de la bodega (debe existir) | GENERAL |
| `sku` | Siempre | SKU del producto (debe existir) | TOR-0001 |
| `cantidad` | Siempre | Cantidad que hay, en unidad base: el stock de la ubicación queda en ella | 1500 |
| `costo_unitario` | No | Costo por unidad base, sin IVA, de lo que entra | 0.08 |

El saldo entra como un **ajuste de inventario confirmado** con motivo "Saldo inicial", uno por bodega,
y queda en el kárdex. La cantidad es la que debe quedar en la ubicación: si ya hay stock, el ajuste
suma o resta la diferencia. Lo que entra lo hace al `costo_unitario` y fija el costo promedio de la
ubicación; sin costo, entra al promedio que tenga la ubicación o al precio de compra del producto.
Con "Solo crear los nuevos" se saltan las ubicaciones que ya tienen stock.

Los servicios no llevan stock. Los lotes y las series se cargan después, desde sus pantallas.

## 6. Errores

Cada error dice la fila (su número en la hoja: la 1 es el encabezado), la columna y qué corregir:

| Código | Qué significa |
|---|---|
| `REQUIRED` | Falta un valor obligatorio |
| `INVALID_VALUE` | El valor no sirve: un número mal escrito, más decimales de los que admite la unidad, una cédula o RUC inválido, un correo mal formado |
| `DUPLICATE_IN_FILE` | La misma clave ya está en una fila anterior del archivo |
| `NOT_FOUND` | No existe la unidad, el producto, la lista, la bodega o la ubicación |
| `ALREADY_IN_USE` | Otro producto ya tiene ese código de barras |
| `NOT_ALLOWED` | La regla no lo permite: la presentación base, stock de un servicio, la lista general sin cantidad mínima, un material de construcción sin IVA 5 |

Si los datos cambian entre la validación y la confirmación (alguien registra el mismo código de
barras, por ejemplo), la importación se **detiene** en esa fila y lo dice. Lo importado hasta ese
momento queda; se corrige el archivo y se vuelve a subir: lo ya importado no se duplica.

## 7. Tiempos

Medido el 2026-11-16 en el entorno local (macOS con OrbStack, PostgreSQL 17 en Docker, el worker
con su configuración por defecto): un archivo de **10.000 productos** (706 KiB) se validó en
**0,8 s** y se importó en **37,6 s** (unas 266 filas por segundo). Cada producto pasa por el mismo
comando que la pantalla, con su presentación base y su entrada de bitácora.

Para repetir la medición:

```bash
IMPORT_VOLUME_ROWS=10000 make test-integration args="tests/integration/postgres/test_imports_volume.py -s"
```
