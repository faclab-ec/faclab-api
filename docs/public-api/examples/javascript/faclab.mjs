// Cliente mínimo de la API pública de Faclab para Node 20+ (fetch nativo, sin
// dependencias).
//
// - Pide el token con client credentials y lo reutiliza hasta un minuto antes
//   de que venza.
// - Cada POST lleva su Idempotency-Key: pasa la misma en los reintentos de una
//   misma operación.
// - Ante 429 espera Retry-After y reintenta.
// - Los errores llegan como FaclabError con el código del catálogo.
//
// Lee FACLAB_API_URL (por defecto http://localhost:3000), FACLAB_CLIENT_ID y
// FACLAB_CLIENT_SECRET.

import { randomUUID } from 'node:crypto'

// Tarifa de cada código de IVA (taxCode de los productos), en porcentaje
export const TAX_RATES = {
    VAT_0: 0n,
    VAT_5: 5n,
    VAT_8_TOURISM: 8n,
    VAT_12: 12n,
    VAT_13: 13n,
    VAT_14: 14n,
    VAT_15: 15n,
    EXEMPT: 0n,
    NOT_TAXED: 0n,
}

// El dinero llega como texto decimal ("12.50"): se calcula en millonésimas con
// BigInt, nunca con números de punto flotante
const toMicros = (amount) => {
    const [whole, fraction = ''] = amount.split('.')
    return BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, '0').slice(0, 6))
}

// a / b redondeado a la mitad hacia arriba (a y b positivos)
const divideHalfUp = (a, b) => (a * 2n + b) / (2n * b)

const formatCents = (cents) =>
    `${cents / 100n}.${String(cents % 100n).padStart(2, '0')}`

/** Lo que cobra Faclab por una línea sin descuento: el subtotal y el IVA, cada
 *  uno redondeado al centavo (mitad hacia arriba) */
export function lineTotal(unitPrice, quantity, taxCode) {
    // millonésimas × millonésimas = billonésimas
    const subtotal = toMicros(unitPrice) * toMicros(quantity)
    const subtotalCents = divideHalfUp(subtotal, 10_000_000_000n)
    const taxCents = divideHalfUp(subtotal * TAX_RATES[taxCode], 1_000_000_000_000n)
    return formatCents(subtotalCents + taxCents)
}

export class FaclabError extends Error {
    constructor(status, error, requestId) {
        super(`${status} ${error.code}: ${error.message} (requestId ${requestId})`)
        this.status = status
        this.code = error.code
        this.field = error.field
        this.requestId = requestId
    }
}

const sleep = (seconds) => new Promise((done) => setTimeout(done, seconds * 1000))

export class Faclab {
    constructor({
        baseUrl = process.env.FACLAB_API_URL ?? 'http://localhost:3000',
        clientId = process.env.FACLAB_CLIENT_ID,
        clientSecret = process.env.FACLAB_CLIENT_SECRET,
    } = {}) {
        this.baseUrl = baseUrl.replace(/\/$/, '')
        this.basic = Buffer.from(`${clientId}:${clientSecret}`).toString('base64')
        this.accessToken = null
        this.expiresAt = 0
    }

    async token() {
        if (this.accessToken && Date.now() < this.expiresAt - 60_000) {
            return this.accessToken
        }
        const response = await fetch(`${this.baseUrl}/api/oauth/token`, {
            method: 'POST',
            headers: {
                Authorization: `Basic ${this.basic}`,
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: 'grant_type=client_credentials',
        })
        if (!response.ok) {
            // El endpoint de token responde como OAuth: {error, error_description}
            throw new Error(`token: ${response.status} ${await response.text()}`)
        }
        const body = await response.json()
        this.accessToken = body.access_token
        this.expiresAt = Date.now() + body.expires_in * 1000
        return this.accessToken
    }

    async request(method, path, { body, params, branchId, idempotencyKey } = {}) {
        const url = new URL(`${this.baseUrl}${path}`)
        for (const [name, value] of Object.entries(params ?? {})) {
            if (value !== undefined && value !== null) url.searchParams.set(name, value)
        }
        const headers = { 'Content-Type': 'application/json' }
        if (branchId !== undefined) headers['X-Branch-Id'] = String(branchId)
        if (method === 'POST') headers['Idempotency-Key'] = idempotencyKey ?? randomUUID()
        let renewed = false
        for (let attempt = 0; attempt < 5; attempt++) {
            headers.Authorization = `Bearer ${await this.token()}`
            const response = await fetch(url, {
                method,
                headers,
                body: body === undefined ? undefined : JSON.stringify(body),
            })
            if (response.status === 429) {
                await sleep(Number(response.headers.get('Retry-After') ?? 1))
                continue
            }
            if (response.status === 401 && !renewed) {
                // Venció mientras tanto: una vez con un token nuevo
                this.accessToken = null
                renewed = true
                continue
            }
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}))
                const error = payload.errors?.[0] ?? {
                    code: `HTTP_${response.status}`,
                    message: response.statusText,
                }
                throw new FaclabError(
                    response.status,
                    error,
                    response.headers.get('X-Request-Id')
                )
            }
            return response
        }
        throw new Error(`${method} ${path}: too many retries`)
    }

    async get(path, params) {
        return (await this.request('GET', path, { params })).json()
    }

    async post(path, body, options = {}) {
        return this.request('POST', path, { ...options, body })
    }

    /** Todas las filas de un listado, página por página (orden estable) */
    async *pages(path, params = {}) {
        const limit = 200
        for (let offset = 0; ; offset += limit) {
            const page = await this.get(path, { ...params, limit, offset })
            yield* page.data
            if (page.data.length < limit) return
        }
    }
}
