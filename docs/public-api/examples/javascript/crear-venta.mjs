// Registra un pedido pagado en línea como venta de Faclab (guía "Ventas desde
// un ecommerce"), lo reintenta con la misma clave y luego lo anula.
//
// 1. Dónde vender: la sucursal, su punto de emisión y una ubicación con stock.
// 2. Qué vender: un producto con stock y su precio con IVA, el que cobra Faclab.
// 3. La venta, con su Idempotency-Key; el reintento recibe la misma respuesta.
// 4. Buscarla por externalReference y anularla (con la factura en camino,
//    Faclab responde INVOICE_IN_PROGRESS: se anula con una nota de crédito).
//
//     node crear-venta.mjs

import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { Faclab, FaclabError, lineTotal } from './faclab.mjs'

// El consumidor final factura hasta este total; con más hace falta el cliente
const FINAL_CONSUMER_LIMIT = 50

const api = new Faclab()

async function chooseProduct(branch) {
    for await (const row of api.pages('/api/v1/stock', { branchId: branch.id })) {
        if (Number(row.available) < 1) continue
        const { data: product } = await api.get(`/api/v1/products/${row.productId}`)
        if (!product.isActive || product.isService) continue
        if (Number(lineTotal(product.salePrice, '1', product.taxCode)) <= FINAL_CONSUMER_LIMIT) {
            return { stock: row, product }
        }
    }
    throw new Error(`la sucursal ${branch.code} no tiene productos con stock`)
}

const { data: branches } = await api.get('/api/v1/branches')
const branch = branches.find((b) => b.emissionPoints.length > 0)
const { stock, product } = await chooseProduct(branch)
const total = lineTotal(product.salePrice, '1', product.taxCode)
const order = `WEB-${randomUUID().slice(0, 8).toUpperCase()}`
const body = {
    emissionPointId: branch.emissionPoints[0].id,
    locationId: stock.locationId,
    externalReference: order,
    items: [{ productId: product.id, quantity: '1' }],
    payments: [{ method: 'TRANSFER', amount: total, reference: `pago-${order}` }],
}

// Una clave por pedido, la misma en cada reintento de ese pedido
const idempotencyKey = randomUUID()
const created = await api.post('/api/v1/sales', body, { branchId: branch.id, idempotencyKey })
const { data: sale } = await created.json()
console.log(
    `venta ${sale.number} (${order}): ${product.sku} por ${sale.total}, factura ${sale.invoiceStatus}`
)
assert.equal(created.status, 201)
assert.equal(Number(sale.total), Number(total))

const retried = await api.post('/api/v1/sales', body, { branchId: branch.id, idempotencyKey })
assert.equal(retried.headers.get('Idempotent-Replayed'), 'true')
assert.equal((await retried.json()).data.id, sale.id)
console.log('reintento con la misma clave: la misma venta (Idempotent-Replayed)')

const { data: found } = await api.get('/api/v1/sales', { externalReference: order })
assert.deepEqual(
    found.map((s) => s.id),
    [sale.id]
)

try {
    await api.post(`/api/v1/sales/${sale.id}/cancel`, { reason: 'Pedido anulado en la tienda' })
    console.log(`venta ${sale.number} anulada: el stock vuelve`)
} catch (error) {
    if (
        !(error instanceof FaclabError) ||
        !['INVOICE_IN_PROGRESS', 'CREDIT_NOTE_REQUIRED'].includes(error.code)
    ) {
        throw error
    }
    console.log(`venta ${sale.number} con factura en camino: ${error.code}`)
}
