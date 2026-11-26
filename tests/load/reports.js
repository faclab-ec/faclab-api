// The back office (S9.2): the listings and reports an administrator opens while the tills sell.
//
//   RATE      requests per minute (default 12)
//   DURATION  default 5m
import { check } from 'k6'
import http from 'k6/http'
import {
    BASE_URL,
    commonOptions,
    fixtures,
    perName,
    pick,
    summary,
    tokenOf,
} from './lib/common.js'

const RATE = Number(__ENV.RATE || 12)

const today = new Date().toISOString().slice(0, 10)
const monthAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10)

const pages = {
    admin_sales: () => '/api/admin/sales?limit=50',
    admin_sales_pending: () => '/api/admin/sales?limit=50&invoiceStatus=PENDING',
    admin_products: () => '/api/admin/products?limit=50&search=Tornillo',
    admin_customers: () => '/api/admin/customers?limit=50&search=Cliente',
    admin_stock: () => '/api/admin/stock?limit=50',
    admin_movements: () => '/api/admin/movements?limit=50',
    admin_receivables: () => '/api/admin/receivables?limit=50',
    admin_audit: () => '/api/admin/audit-log?limit=50',
    report_valuation: () => '/api/admin/reports/inventory/valuation',
    report_kardex: () =>
        `/api/admin/reports/inventory/kardex?productId=${pick(fixtures.products).id}`,
    pos_daily: () => `/api/pos/reports/daily?date=${today}`,
    pos_methods: () =>
        `/api/pos/reports/by-payment-method?fromDate=${monthAgo}&toDate=${today}`,
}

export const options = {
    ...commonOptions,
    scenarios: {
        office: {
            executor: 'constant-arrival-rate',
            rate: RATE,
            timeUnit: '1m',
            duration: __ENV.DURATION || '5m',
            preAllocatedVUs: 4,
            maxVUs: 10,
            gracefulStop: '60s',
        },
    },
    thresholds: perName(Object.keys(pages)),
}

export default function () {
    const name = __ENV.ONLY || pick(Object.keys(pages))
    const response = http.get(`${BASE_URL}${pages[name]()}`, {
        headers: { Authorization: `Bearer ${tokenOf(fixtures.admin)}` },
        tags: { name },
        timeout: '120s',
    })
    if (!check(response, { [`${name} 200`]: (r) => r.status === 200 })) {
        console.warn(`${name} ${response.status}: ${String(response.body).slice(0, 200)}`)
    }
}

export const handleSummary = summary
