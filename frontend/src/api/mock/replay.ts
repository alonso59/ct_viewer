// Replay of API exchanges recorded from the real backend on the synthetic fixtures (TST-04,
// AUD-A6-03). `recorded.json` is written by `make record-mock` (backend/tools/record_mock.py);
// never edit it by hand. A request is answered by the recording with the same method, path,
// query (paging parameters dropped) and JSON body; failing that, the same request with any body;
// failing that (GET only), the same path without its query. Nothing else is computed here: an
// unrecorded request is a `not-recorded` problem, and a write changes no later answer.
import recorded from './recorded.json'

interface Exchange {
  method: string
  path: string
  query: string
  body: unknown
  status: number
  response: unknown
}
interface Recording {
  project_id: string
  exchanges: Exchange[]
}
const rec = recorded as unknown as Recording

/** The recorded demo project (the recorder's fixed id) */
export const RECORDED_PID = rec.project_id

const PAGING = new Set(['limit', 'cursor'])

/** Sorted-key JSON, so equal bodies give equal keys */
function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`
  if (v && typeof v === 'object')
    return `{${Object.keys(v)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonical((v as Record<string, unknown>)[k])}`)
      .join(',')}}`
  return JSON.stringify(v ?? null)
}

function queryKey(q: URLSearchParams): string {
  return JSON.stringify([...q.entries()].filter(([k]) => !PAGING.has(k)).sort(([a, x], [b, y]) => a.localeCompare(b) || x.localeCompare(y)))
}

const exact = new Map<string, Exchange>()
const anyBody = new Map<string, Exchange>()
const anyQuery = new Map<string, Exchange>()
for (const e of rec.exchanges) {
  const route = `${e.method} ${e.path}`
  const q = `${route} ${queryKey(new URLSearchParams(e.query))}`
  exact.set(`${q} ${canonical(e.body)}`, e)
  anyBody.set(q, e)
  // the unfiltered recording is the fallback of its path
  if (!e.query || !anyQuery.has(route)) anyQuery.set(route, e)
}

/** Recorded exchanges (read-only), e.g. for the contract test against the OpenAPI snapshot */
export const exchanges: readonly Exchange[] = rec.exchanges

export function lookup(method: string, url: URL, body: unknown): Exchange | undefined {
  const route = `${method} ${url.pathname}`
  const q = `${route} ${queryKey(url.searchParams)}`
  return exact.get(`${q} ${canonical(body ?? null)}`) ?? anyBody.get(q) ?? (method === 'GET' ? anyQuery.get(route) : undefined)
}

/** Prototype latency so loading states show; none under Vitest (AUD-A6-15) */
const LATENCY_MS = import.meta.env.MODE === 'test' ? 0 : 60

async function bodyOf(input: RequestInfo | URL, init?: RequestInit): Promise<unknown> {
  const raw = input instanceof Request ? await input.clone().text() : typeof init?.body === 'string' ? init.body : null
  if (!raw) return null
  try {
    return JSON.parse(raw) as unknown
  } catch {
    return null
  }
}

const json = (status: number, v: unknown) =>
  new Response(status === 204 || v == null ? null : JSON.stringify(v), { status, headers: { 'content-type': 'application/json' } })

/** A `fetch` that answers from the recording (no network, R5) */
export async function replayFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const req = input instanceof Request ? input : null
  const method = (init?.method ?? req?.method ?? 'GET').toUpperCase()
  const url = new URL(req ? req.url : String(input), 'http://mock.invalid')
  const body = method === 'GET' ? null : await bodyOf(input, init)
  if (LATENCY_MS) await new Promise((r) => setTimeout(r, LATENCY_MS))
  const hit = lookup(method, url, body)
  if (hit) return json(hit.status, structuredClone(hit.response))
  return json(501, {
    type: '/problems/not-recorded',
    title: 'Not available in the mock',
    status: 501,
    detail: `${method} ${url.pathname} was not recorded (make record-mock)`,
  })
}
