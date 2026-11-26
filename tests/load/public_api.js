// The public API (S9.2): an integration client that syncs catalog and stock and creates sales, as an
// online store would.
//
//   READ_RATE   reads per second (default 5): products and stock pages, a third of them incremental
//   SALES_RATE  sales per minute (default 4)
//   DURATION    default 5m
//
// 429s are counted apart (rate_limited): with the default limits (600/min and a burst of 50 per
// client) they are the expected answer past them, and each must carry Retry-After.
import { check, fail } from 'k6'
import http from 'k6/http'
import { Counter } from 'k6/metrics'
import {
    BASE_URL,
    commonOptions,
    fixtures,
    perName,
    pick,
    randomInt,
    summary,
    uuid,
} from './lib/common.js'

const READ_RATE = Number(__ENV.READ_RATE || 5)
const SALES_RATE = Number(__ENV.SALES_RATE || 4)
const DURATION = __ENV.DURATION || '5m'

const sales = new Counter('sales_ok')
const rejected = new Counter('sales_rejected')
const limited = new Counter('rate_limited')
const cheap = fixtures.products.filter((p) => p.cents <= 300)

const scenario = (exec, rate, timeUnit, vus) => ({
    executor: 'constant-arrival-rate',
    exec,
    rate,
    timeUnit,
    duration: DURATION,
    preAllocatedVUs: vus,
    maxVUs: vus,
})

export const options = {
    ...commonOptions,
    scenarios: {
        ...(READ_RATE > 0 && {
            sync: scenario('sync', READ_RATE, '1s', Math.min(Math.max(4, READ_RATE), 100)),
        }),
        ...(SALES_RATE > 0 && {
            store: scenario('store', SALES_RATE, '1m', Math.min(Math.max(2, Math.ceil(SALES_RATE / 20)), 100)),
        }),
    },
    thresholds: perName(['v1_products', 'v1_products_since', 'v1_stock', 'v1_sale']),
}

let cached = null

function token() {
    if (cached && Date.now() - cached.at < 10 * 60 * 1000) return cached.token
    const response = http.post(
        `${BASE_URL}/api/oauth/token`,
        {
            grant_type: 'client_credentials',
            client_id: fixtures.client.id,
            client_secret: fixtures.client.secret,
        },
        { tags: { name: 'oauth' } }
    )
    if (!check(response, { 'token 200': (r) => r.status === 200 })) {
        fail(`token: ${response.status} ${response.body}`)
    }
    cached = { token: response.json('access_token'), at: Date.now() }
    return cached.token
}

function isLimited(response) {
    if (response.status !== 429) return false
    limited.add(1)
    check(response, { '429 with Retry-After': (r) => !!r.headers['Retry-After'] })
    return true
}

export function sync() {
    const params = (name) => ({
        headers: { Authorization: `Bearer ${token()}` },
        tags: { name },
    })
    const kind = Math.random()
    let response
    if (kind < 0.4) {
        const offset = randomInt(0, 49) * 200
        response = http.get(
            `${BASE_URL}/api/v1/products?limit=200&offset=${offset}`,
            params('v1_products')
        )
    } else if (kind < 0.7) {
        const since = new Date(Date.now() - 5 * 60 * 1000).toISOString()
        response = http.get(
            `${BASE_URL}/api/v1/products?limit=200&updatedSince=${since}`,
            params('v1_products_since')
        )
    } else {
        const branch = pick(fixtures.branches)
        const offset = randomInt(0, 49) * 200
        response = http.get(
            `${BASE_URL}/api/v1/stock?limit=200&offset=${offset}&branchId=${branch.id}`,
            params('v1_stock')
        )
    }
    if (!isLimited(response)) check(response, { 'read 200': (r) => r.status === 200 })
}

export function store() {
    const branch = pick(fixtures.branches)
    const items = []
    let subtotal = 0
    for (let n = randomInt(1, 3); n > 0; n--) {
        const product = pick(cheap)
        if (items.some((i) => i.productId === product.id)) continue
        const quantity = randomInt(1, 3)
        items.push({ productId: product.id, quantity: String(quantity) })
        subtotal += product.cents * quantity
    }
    const total = subtotal + Math.floor((subtotal * 15 + 50) / 100)
    const response = http.post(
        `${BASE_URL}/api/v1/sales`,
        JSON.stringify({
            emissionPointId: branch.emissionPointId,
            locationId: branch.locationId,
            externalReference: uuid(),
            items,
            payments: [{ method: 'TRANSFER', amount: (total / 100).toFixed(2) }],
        }),
        {
            headers: {
                Authorization: `Bearer ${token()}`,
                'Content-Type': 'application/json',
                'X-Branch-Id': String(branch.id),
                'Idempotency-Key': uuid(),
            },
            tags: { name: 'v1_sale' },
            timeout: '60s',
        }
    )
    if (isLimited(response)) return
    if (check(response, { 'sale 201': (r) => r.status === 201 || r.status === 200 })) {
        sales.add(1)
    } else {
        rejected.add(1)
        console.warn(`v1 sale ${response.status}: ${String(response.body).slice(0, 300)}`)
    }
}

export const handleSummary = summary
