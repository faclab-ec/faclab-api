# ADR-0012: Numeración de documentos internos y tributarios

- **Estado:** propuesto (2026-10-14)
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

## Consecuencias

- Se elimina la carrera de la orden de compra y la del secuencial.
- Bloquear la fila del contador serializa la creación de documentos del mismo tipo en la misma sucursal.
  Es aceptable para el volumen de una ferretería y se mide en S9.2.
