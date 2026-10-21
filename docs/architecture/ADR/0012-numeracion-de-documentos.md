# ADR-0012: Numeración de documentos internos y tributarios

- **Estado:** aceptado (2026-10-19; ventas y devoluciones del POS desde S2.6, comprobantes desde S2.8)
- **Relacionado:** [ADR-0004](0004-persistencia-de-facturacion-en-postgresql.md), [MULTI_TENANCY.md](../MULTI_TENANCY.md)

## Contexto

- Las ventas, devoluciones, ajustes y transferencias no tienen número.
- La orden de compra usa `MAX()` y falla en concurrencia (G-33).
- El secuencial del SRI es global y puede repetirse (G-09).
- El SRI exige un secuencial de 9 dígitos por establecimiento, punto de emisión y tipo de comprobante.

## Decisión

- **Documentos internos** (venta, cotización, orden de compra, devolución, ajuste, transferencia,
  cierre de caja):
  - Los numera el core con una tabla `document_sequences (tenant_id, branch_id, doc_type, next_value)`.
  - Se usa `UPDATE ... SET next_value = next_value + 1 RETURNING` dentro de la transacción del
    documento y `UNIQUE (tenant_id, branch_id, doc_type, number)`.
  - El formato es configurable por empresa, por ejemplo `V-001-000123`.
- **Comprobantes electrónicos** (factura, nota de crédito):
  - Los numera **facturación**, que es dueña del secuencial ante el SRI, con la misma técnica sobre
    `sequences (tenant_id, establishment, emission_point, doc_type)`.
  - El valor inicial es configurable para continuar la numeración de un sistema anterior y nunca puede
    retroceder.
  - Un rechazo consume el secuencial (comportamiento actual).
- El core envía en el mensaje el establecimiento y el punto de emisión de la venta (ADR-0006);
  facturación no los decide.

### Precisiones de la implementación (S2.6)

- `document_sequences (id, tenant_id, branch_id, doc_type, last_value)` en `src/organization/`, con
  `UNIQUE (tenant_id, branch_id, doc_type)`, FK compuesta a la sucursal y RLS forzado. Guarda el último
  número emitido, no el siguiente: cada número es un upsert atómico,
  `INSERT … ON CONFLICT DO UPDATE SET last_value = last_value + 1 RETURNING last_value`, así el primer
  documento de un tipo crea el contador en 1 sin un paso de alta
  (`SqlAlchemyDocumentSequenceRepository`, también en SQLite para las pruebas).
- `DocumentNumbering.next(branch_id, doc_type)` lo formatea con el código de establecimiento de la
  sucursal: `V-001-000123` (ventas) y `D-001-000045` (devoluciones). El documento guarda el número ya
  formateado, que conserva el código con el que se emitió. Unicidad en el documento:
  `uq_sales_tenant_branch_number` y `uq_pos_refunds_tenant_branch_number`.
- El número se asigna cuando el documento surte efecto (venta confirmada, devolución procesada): un
  borrador descartado o una devolución cancelada no consumen números, y una venta cancelada conserva
  el suyo. Si la operación falla, el rollback deshace también el contador.
- Orden de bloqueos: cada documento del POS bloquea primero sus filas de stock (por producto) y al
  final el contador, así dos ventas de productos distintos solo se esperan en el número y no hay
  ciclos entre ventas y devoluciones.
- El formato es fijo por ahora; el formato configurable por empresa y la numeración de cotizaciones,
  órdenes de compra, ajustes, transferencias y cierres quedan para sus sesiones (anotado en
  ROADMAP.md).

### Precisiones de la implementación (S2.8, comprobantes)

- `sequences (tenant_id, establishment, emission_point, doc_type, last_value)` en faclab-invoicing,
  con la misma técnica: `INSERT … ON CONFLICT DO UPDATE SET last_value = last_value + 1 RETURNING`,
  dentro de la transacción que guarda el número en la factura (`PgInvoiceRepository.assignSequence`).
  Si la factura cambió mientras tanto, el rollback devuelve el número.
- `uq_invoices_tenant_number UNIQUE (tenant_id, establishment, emission_point, sequence)`.
- El valor inicial se fija por establecimiento y punto de emisión con
  `PUT /api/sequences/{establishment}/{emissionPoint}`; un valor menor que el último emitido responde
  `SEQUENCE_CANNOT_GO_BACK` (409). Guardar el perfil fiscal nunca lo mueve.
- El establecimiento y el punto de emisión llegan en `sales.confirmed` v2 (los de la terminal de la
  venta); facturación no los decide. Una venta sin punto de emisión no se publica
  (`SALE_WITHOUT_EMISSION_POINT`).
- Bloquear el cambio del código de establecimiento o de punto de emisión cuando ya hay comprobantes
  sigue pendiente (ROADMAP.md).

## Consecuencias

- Se elimina la carrera de la orden de compra y la del secuencial.
- Bloquear la fila del contador serializa la creación de documentos del mismo tipo en la misma sucursal.
  Es aceptable para el volumen de una ferretería y se mide en S9.2.
