// Receptor de webhooks de Faclab (guías "Webhooks" y "Facturas por webhook").
//
// Comprueba la firma Standard Webhooks, rechaza mensajes de más de 5 minutos,
// responde 204 de inmediato y procesa después, una sola vez por webhook-id.
// Ante invoice.authorized pide la factura a la API y guarda su RIDE.
//
//     FACLAB_WEBHOOK_SECRET=whsec_... node receptor-webhooks.mjs
//
// - FACLAB_WEBHOOK_SECRET: el secreto del endpoint (GET …/secret). En su lugar,
//   FACLAB_WEBHOOK_SECRET_FILE: un archivo que lo contiene, leído en cada
//   mensaje (sirve para rotarlo sin reiniciar).
// - FACLAB_WEBHOOK_PORT (8000) y FACLAB_WEBHOOK_BIND (127.0.0.1).
// - Con FACLAB_CLIENT_ID y FACLAB_CLIENT_SECRET, descarga las facturas
//   autorizadas en FACLAB_INVOICES_DIR (./facturas).
//
// En producción va detrás de HTTPS: Faclab solo envía a URLs https públicas.

import crypto from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { join } from 'node:path'

const TOLERANCE_SECONDS = 300

function secret() {
    const file = process.env.FACLAB_WEBHOOK_SECRET_FILE
    const value = file
        ? readFileSync(file, 'utf8').trim()
        : process.env.FACLAB_WEBHOOK_SECRET
    return Buffer.from(value.replace(/^whsec_/, ''), 'base64')
}

/** La firma de `{id}.{timestamp}.{cuerpo}` con HMAC-SHA256, sobre el cuerpo tal
 *  como llegó. Durante una rotación el encabezado trae dos firmas */
export function verify(msgId, timestamp, rawBody, header) {
    const sent = Number(timestamp)
    if (!Number.isFinite(sent) || Math.abs(Date.now() / 1000 - sent) > TOLERANCE_SECONDS) {
        return false
    }
    const expected = crypto
        .createHmac('sha256', secret())
        .update(`${msgId}.${timestamp}.`)
        .update(rawBody)
        .digest('base64')
    return (header ?? '').split(' ').some((signature) => {
        if (!signature.startsWith('v1,')) return false
        const given = Buffer.from(signature.slice(3))
        return (
            given.length === Buffer.byteLength(expected) &&
            crypto.timingSafeEqual(given, Buffer.from(expected))
        )
    })
}

const seen = new Set()

async function downloadInvoice(invoiceId) {
    const { Faclab } = await import('./faclab.mjs')
    const api = new Faclab()
    const { data: invoice } = await api.get(`/api/v1/invoices/${invoiceId}`)
    const folder = process.env.FACLAB_INVOICES_DIR ?? 'facturas'
    mkdirSync(folder, { recursive: true })
    const ride = await api.request('GET', `/api/v1/invoices/${invoiceId}/ride`)
    writeFileSync(join(folder, `${invoice.accessCode}.pdf`), Buffer.from(await ride.arrayBuffer()))
    console.log(`  factura ${invoice.number} guardada en ${folder}`)
}

async function processEvent(event) {
    const { data } = event
    console.log(`verificado ${event.type} ${event.id}`)
    if (event.type === 'invoice.authorized') {
        console.log(`  venta ${data.saleNumber}: factura ${data.invoiceId}`)
        if (process.env.FACLAB_CLIENT_ID) await downloadInvoice(data.invoiceId)
    } else if (event.type === 'invoice.rejected') {
        console.log(`  venta ${data.saleNumber} rechazada: ${data.reason}`)
    } else if (event.type === 'credit_note.authorized') {
        console.log(`  nota de crédito ${data.number} de la venta ${data.saleId}`)
    }
}

const server = createServer((request, response) => {
    const chunks = []
    request.on('data', (chunk) => chunks.push(chunk))
    request.on('end', () => {
        const rawBody = Buffer.concat(chunks)
        const msgId = request.headers['webhook-id'] ?? ''
        const ok = verify(
            msgId,
            request.headers['webhook-timestamp'],
            rawBody,
            request.headers['webhook-signature']
        )
        // Rápido: el trabajo se hace fuera de la solicitud
        response.writeHead(ok ? 204 : 401).end()
        if (!ok) {
            console.log(`firma inválida ${msgId}`)
            return
        }
        if (seen.has(msgId)) return // un reintento de algo ya recibido
        seen.add(msgId)
        setImmediate(() =>
            processEvent(JSON.parse(rawBody)).catch((error) =>
                console.log(`error procesando ${msgId}: ${error.message}`)
            )
        )
    })
})

const port = Number(process.env.FACLAB_WEBHOOK_PORT ?? 8000)
const bind = process.env.FACLAB_WEBHOOK_BIND ?? '127.0.0.1'
server.listen(port, bind, () => console.log(`escuchando en http://${bind}:${port}`))
