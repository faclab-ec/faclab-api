// What the load scenarios share (S9.2): the guard against real deployments, the data setup_data.py
// wrote, the session of each virtual user and the summary of a run.
import { check, fail } from 'k6'
import http from 'k6/http'

export const fixtures = JSON.parse(open(__ENV.FIXTURES || '/data/fixtures.json'))
export const BASE_URL = ensureTestHost(__ENV.BASE_URL || fixtures.baseUrl)

/** The load tests write thousands of documents: never against a real deployment. */
function ensureTestHost(url) {
    const host = url.replace(/^https?:\/\//, '').split(/[:/]/)[0]
    if (host !== 'localhost' && host !== '127.0.0.1' && !host.endsWith('.test')) {
        throw new Error(`${host} is not a test environment (local or *.test)`)
    }
    return url.replace(/\/$/, '')
}

// Staging's certificate is from Caddy's internal CA; the guard above keeps this to test hosts
export const commonOptions = {
    insecureSkipTLSVerify: true,
    summaryTrendStats: ['count', 'avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
    discardResponseBodies: false,
    setupTimeout: '60s',
}

export const pick = (list) => list[Math.floor(Math.random() * list.length)]

export const randomInt = (min, max) => min + Math.floor(Math.random() * (max - min + 1))

export function uuid() {
    return 'xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx'.replace(/x/g, () =>
        Math.floor(Math.random() * 16).toString(16)
    )
}

let sessions = {}

/** Sessions opened once in setup(), so a ramp of virtual users doesn't become a ramp of logins
 * (each one costs a bcrypt check). */
export function openSessions(users) {
    return users.map((user) => ({ username: user.username, token: tokenOf(user), at: Date.now() }))
}

export function useSessions(opened) {
    for (const session of opened) {
        if (!sessions[session.username]) sessions[session.username] = session
    }
}

/** The access token of a user, renewed before its 15 minutes end. One cache per virtual user. */
export function tokenOf(user) {
    const cached = sessions[user.username]
    if (cached && Date.now() - cached.at < 10 * 60 * 1000) return cached.token
    const response = http.post(
        `${BASE_URL}/api/auth/login`,
        JSON.stringify({ username: user.username, password: user.password }),
        { headers: { 'Content-Type': 'application/json' }, tags: { name: 'login' } }
    )
    if (!check(response, { 'login 200': (r) => r.status === 200 })) {
        fail(`login of ${user.username}: ${response.status} ${response.body}`)
    }
    const token = response.json('data.accessToken')
    sessions[user.username] = { token, at: Date.now() }
    return token
}

/** Thresholds that never fail: they make k6 report each request name apart. */
export function perName(names) {
    const thresholds = {}
    for (const name of names) {
        thresholds[`http_req_duration{name:${name}}`] = ['max>=0']
        thresholds[`http_req_failed{name:${name}}`] = ['rate>=0']
    }
    return thresholds
}

export function summary(data) {
    const line = (key) => {
        const v = data.metrics[key].values
        return `${key.padEnd(52)} n=${v.count} med=${v.med.toFixed(0)} p95=${v['p(95)'].toFixed(0)} p99=${v['p(99)'].toFixed(0)} max=${v.max.toFixed(0)}`
    }
    const lines = Object.keys(data.metrics)
        .filter((k) => data.metrics[k].values['p(95)'] !== undefined && /_duration/.test(k))
        .filter((k) => data.metrics[k].values.count > 0)
        .sort()
        .map(line)
    for (const key of Object.keys(data.metrics).sort()) {
        const metric = data.metrics[key]
        if (metric.type === 'counter' && /^(sales|api|errors|iterations|dropped|rate_limited)/.test(key)) {
            lines.push(`${key}: ${metric.values.count} (${metric.values.rate.toFixed(2)}/s)`)
        }
    }
    const failed = data.metrics.http_req_failed
    if (failed) lines.push(`http_req_failed: ${(failed.values.rate * 100).toFixed(2)} %`)
    const output = { stdout: lines.join('\n') + '\n' }
    if (__ENV.SUMMARY) output[__ENV.SUMMARY] = JSON.stringify(data)
    return output
}
