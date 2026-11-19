// Sincroniza productos, listas de precios y stock (guía "Sincronizar catálogo y
// stock").
//
// La primera vez trae todo; después, solo lo cambiado desde la sincronización
// anterior, cuyo momento se guarda en FACLAB_SYNC_STATE (por defecto
// .faclab-sync-js). Como updatedSince es inclusivo, una fila del borde puede
// repetirse: se guarda por id, nunca se inserta dos veces.
//
//     node sincronizar-catalogo.mjs

import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { Faclab } from './faclab.mjs'

const STATE = process.env.FACLAB_SYNC_STATE ?? '.faclab-sync-js'

const api = new Faclab()
const since = existsSync(STATE) ? readFileSync(STATE, 'utf8').trim() : null
// El momento en que empieza: la próxima vez se pide lo cambiado desde aquí
const started = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')

const products = new Map()
for await (const product of api.pages(
    '/api/v1/products',
    since ? { updatedSince: since } : {}
)) {
    products.set(product.id, product)
}
console.log(`productos ${since ? 'cambiados' : 'en total'}: ${products.size}`)

const priceLists = []
for await (const priceList of api.pages('/api/v1/price-lists')) {
    priceLists.push(priceList.name)
}
console.log(`listas de precios: ${priceLists.join(', ')}`)

const { data: branches } = await api.get('/api/v1/branches')
for (const branch of branches) {
    // Disponible por SKU en todas las ubicaciones de la sucursal, en unidades
    // base. Se suma como texto decimal: aquí basta con saber si hay
    const withStock = new Set()
    for await (const row of api.pages('/api/v1/stock', { branchId: branch.id })) {
        if (Number(row.available) > 0) withStock.add(row.sku)
    }
    console.log(
        `sucursal ${branch.code} ${branch.name}: ${withStock.size} productos con stock`
    )
}

writeFileSync(STATE, started)
console.log(`próxima sincronización: updatedSince=${started}`)
if (!since && products.size === 0) {
    console.error('la empresa no tiene productos')
    process.exit(1)
}
