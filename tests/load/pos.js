// The checkout of the POS (S9.2): search, scan, price, quick sale and receipt at the six tills.
//
//   RATE      sales per minute (default 4, the morning peak of the pilot hardware store)
//   DURATION  how long they arrive (default 10m)
//   MODE      normal (the whole catalog) | contention (every till of one branch sells the same
//             five products, so the sales meet on the same stock rows)
//
// Every sale is paid; a tenth goes on credit. The final consumer's stay under USD 50, which is what
// faclab-invoicing accepts without identifying the buyer.
import { check, sleep } from 'k6'
import http from 'k6/http'
import { Counter, Trend } from 'k6/metrics'
import exec from 'k6/execution'
import {
    BASE_URL,
    commonOptions,
    fixtures,
    perName,
    pick,
    randomInt,
    summary,
    tokenOf,
    uuid,
} from './lib/common.js'

const RATE = Number(__ENV.RATE || 4)
const DURATION = __ENV.DURATION || '10m'
const MODE = __ENV.MODE || 'normal'
const MAX_VUS = Number(__ENV.MAX_VUS || Math.min(Math.max(6, Math.ceil(RATE / 10)), 150))

const sales = new Counter('sales_ok')
const rejected = new Counter('sales_rejected')
const lines = new Counter('sales_lines')
const checkout = new Trend('checkout_duration', true)

const tills = fixtures.branches.flatMap((branch) =>
    branch.terminals.map((terminal) => ({ ...terminal, branchId: branch.id }))
)
const contentionTills = tills.filter((t) => t.branchId === fixtures.branches[0].id)
const cheap = fixtures.products.filter((p) => p.cents <= 300)
const hot = fixtures.products.slice(0, 5)

export const options = {
    ...commonOptions,
    scenarios: {
        checkout: {
            executor: 'constant-arrival-rate',
            rate: RATE,
            timeUnit: '1m',
            duration: DURATION,
            preAllocatedVUs: MAX_VUS,
            maxVUs: MAX_VUS,
            gracefulStop: '60s',
        },
    },
    thresholds: perName(['search', 'barcode', 'resolve', 'quick', 'receipt']),
}

// The share of sales: 1-8 lines, three on average
const lineCount = () => pick([1, 1, 2, 2, 2, 3, 3, 4, 5, 8])

function basket(source) {
    const chosen = new Map()
    const wanted = Math.min(lineCount(), source.length)
    while (chosen.size < wanted) {
        const product = pick(source)
        chosen.set(product.id, { product, quantity: randomInt(1, 3) })
    }
    return [...chosen.values()]
}

export default function () {
    const pool = MODE === 'contention' ? contentionTills : tills
    const till = pool[exec.vu.idInTest % pool.length]
    const token = tokenOf(till)
    const headers = {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        'X-Branch-Id': String(till.branchId),
        'X-Terminal-Id': String(till.id),
    }
    const get = (path, name) => http.get(`${BASE_URL}${path}`, { headers, tags: { name } })

    const kind = Math.random()
    const finalConsumer = kind < 0.7
    const onCredit = kind >= 0.9
    const customerId = finalConsumer
        ? null
        : pick(onCredit ? fixtures.creditCustomers : fixtures.listCustomers)
    let items = basket(MODE === 'contention' ? hot : finalConsumer ? cheap : fixtures.products)
    const started = Date.now()

    // The cashier types a name for the first product and scans the rest
    get(`/api/pos/products/search?term=${encodeURIComponent(items[0].product.term)}&limit=20`, 'search')
    for (const item of items.slice(1, 4)) {
        if (item.product.barcode) {
            get(`/api/pos/products/barcode?code=${item.product.barcode}`, 'barcode')
        }
    }
    const resolved = http.post(
        `${BASE_URL}/api/pos/prices/resolve`,
        JSON.stringify({
            customerId,
            items: items.map((i) => ({ productId: i.product.id, quantity: i.quantity })),
        }),
        { headers, tags: { name: 'resolve' } }
    )
    if (!check(resolved, { 'resolve 200': (r) => r.status === 200 })) {
        rejected.add(1, { code: `resolve_${resolved.status}` })
        return
    }
    const prices = {}
    for (const price of resolved.json('data')) prices[price.productId] = Number(price.unitPrice)

    // VAT 15 % over the subtotal, half up, in cents (every product of the test is taxed at 15)
    const totalOf = (list) => {
        const subtotal = list.reduce(
            (sum, i) => sum + Math.round(prices[i.product.id] * 100) * i.quantity,
            0
        )
        return subtotal + Math.floor((subtotal * 15 + 50) / 100)
    }
    while (finalConsumer && totalOf(items) > 4900) {
        if (items.length > 1) items = items.slice(0, -1)
        else items[0].quantity = 1
        if (items.length === 1 && items[0].quantity === 1) break
    }
    const total = totalOf(items) / 100

    const body = {
        customerId,
        items: items.map((i) => ({ productId: i.product.id, quantity: i.quantity })),
        payments: [
            onCredit
                ? { amount: total, paymentMethod: 'CREDIT' }
                : { amount: Math.ceil(total / 5) * 5, paymentMethod: 'CASH' },
        ],
    }
    const response = http.post(`${BASE_URL}/api/pos/sales/quick`, JSON.stringify(body), {
        headers: { ...headers, 'Idempotency-Key': uuid() },
        tags: { name: 'quick' },
        timeout: '60s',
    })
    if (!check(response, { 'sale 2xx': (r) => r.status >= 200 && r.status < 300 })) {
        const code = response.status ? response.json('errors.0.code') : 'timeout'
        rejected.add(1, { code: String(code) })
        console.warn(`sale ${response.status}: ${String(response.body).slice(0, 300)}`)
        return
    }
    sales.add(1)
    lines.add(items.length)
    get(`/api/pos/sales/${response.json('data.id')}/receipt`, 'receipt')
    checkout.add(Date.now() - started)
    sleep(0.1)
}

export const handleSummary = summary
