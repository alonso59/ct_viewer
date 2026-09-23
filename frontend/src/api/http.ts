// HTTP binding of the API surface (backend/API.md). Built endpoints go through the typed
// openapi-fetch client (FE-03); endpoints whose backend is not merged yet use the documented paths
// with hand-written types (types.ts), and their list reads treat a missing route as empty.
import createClient from 'openapi-fetch'

import { ProblemError, toProblemError } from './problem'
import type { paths } from './schema'
import type { Api, CaseFilter, ConnectionState } from './surface'
import type {
  DerivedDef,
  ExternalImportResult,
  CaseDetail,
  CaseSummary,
  FsListing,
  ItemRecord,
  Job,
  Preset,
  Project,
  ProjectSummary,
  QCWarning,
  ServerEvent,
  Variable,
} from './types'

/** API base URL; empty = same origin (FE-07: configurable for Electron) */
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
const V1 = `${BASE}/api/v1`
const PAGE = 2000

const client = createClient<paths>({ baseUrl: BASE })

type Res<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(p: Promise<Res<T>>): Promise<T> {
  const { data, error, response } = await p
  if (!response.ok) throw toProblemError(response.status, error, response.statusText)
  return data as T
}

async function send<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const init: RequestInit = { method, headers: { ...headers } }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    ;(init.headers as Record<string, string>)['content-type'] = 'application/json'
  }
  const r = await fetch(`${V1}${path}`, init)
  const json: unknown = r.status === 204 ? null : await r.json().catch(() => null)
  if (!r.ok) throw toProblemError(r.status, json, r.statusText)
  return json as T
}

/** List reads of endpoints that may not exist yet: a missing route is an empty list */
async function listOrEmpty<T>(path: string): Promise<T[]> {
  try {
    const v = await send<T[] | { items: T[] }>('GET', path)
    return Array.isArray(v) ? v : v.items
  } catch (e) {
    if (e instanceof ProblemError && (e.status === 404 || e.status === 405)) return []
    throw e
  }
}

const enc = encodeURIComponent
const reviewerHeader = (reviewer: string) => ({ 'X-Reviewer': reviewer })

type RawCase = paths['/api/v1/projects/{pid}/cases']['get']['responses']['200']['content']['application/json']['items'][number] &
  Partial<Pick<CaseSummary, 'variables' | 'thumb_item_id' | 'excluded'>>

function normalizeCase(c: RawCase): CaseSummary {
  return {
    patient_id: null,
    phases: [],
    last_reviewed_at: null,
    ...c,
    curation_status: (c.curation_status ?? 'not_reviewed') as CaseSummary['curation_status'],
    variables: c.variables ?? {},
    thumb_item_id: c.thumb_item_id ?? null,
    excluded: c.excluded ?? false,
  }
}

const normalizeItem = (i: paths['/api/v1/projects/{pid}/cases/{cid}']['get']['responses']['200']['content']['application/json']['scans'][number]['items'][number]): ItemRecord => ({
  patient_id: null,
  image: null,
  mask: null,
  geometry: null,
  labels_present: [],
  warning_codes: [],
  extra: {},
  ...i,
})

type Schemas = import('./schema').components['schemas']

const normalizeProject = (p: Schemas['ProjectDetail']): Project => ({
  path_roots: [],
  phase_vocabulary: [],
  phase_priority: [],
  viewer_defaults: { ww: 400, wl: 50, layout: 'four-up' },
  ...p,
  phase_mapping: p.phase_mapping ?? {},
  label_map: p.label_map ?? [],
})

// API-16..18 return the whole Catalog; the UI works on Variable[] (profile names differ too).
type Catalog = Schemas['Catalog']
type ExternalReport = Schemas['ExternalReport']

type WireDerived = NonNullable<Catalog['derived']>[number]

/** UI: `quantiles` = number of groups; API: cut probabilities in (0, 1). */
function toWireDerived(d: DerivedDef): WireDerived {
  if (d.op !== 'bin' || d.quantiles == null) return d as WireDerived
  const n = d.quantiles
  return { ...d, quantiles: Array.from({ length: n - 1 }, (_, i) => (i + 1) / n) }
}

function fromWireDerived(d: WireDerived): DerivedDef {
  if (d.op !== 'bin' || d.quantiles == null) return d as DerivedDef
  return { ...d, quantiles: d.quantiles.length + 1, thresholds: d.thresholds ?? undefined, labels: d.labels ?? [] }
}

function catalogToVariables(c: Catalog): Variable[] {
  const derived = c.derived ?? []
  return (c.variables ?? []).map((v) => {
    const p = v.profile
    return {
      ...v,
      tags: v.tags ?? [],
      profile: {
        missing_pct: p.missing_pct,
        n_distinct: p.distinct,
        examples: p.examples ?? [],
        min: p.min ?? null,
        max: p.max ?? null,
        levels: (p.top ?? []).map((x) => ({ value: x.value, count: x.n })),
      },
      definition: (() => {
        const d = derived.find((x) => x.name === v.name)
        return d ? fromWireDerived(d) : null
      })(),
    }
  })
}

function variableFrom(c: Catalog, name: string): Variable {
  const v = catalogToVariables(c).find((x) => x.name === name)
  if (!v) throw new Error(`variable ${name} missing from catalog response`)
  return v
}

const externalResult = (r: ExternalReport, key: 'case_id' | 'patient_id'): ExternalImportResult => ({
  key,
  n_rows: r.n_rows,
  matched: r.n_matched,
  unmatched_keys: r.unmatched_keys ?? [],
  added: r.table.columns ?? [],
})

const normalizeWarning = (w: Schemas['QcWarning']): QCWarning => ({ case_id: null, field: null, item_id: null, path_ref: null, ...w })

const normalizeJob = (j: Schemas['JobInfo']): Job => ({
  eta_s: null,
  started_at: null,
  finished_at: null,
  ref: null,
  error: null,
  ...j,
})

const normalizeFs = (l: Schemas['FsListing']): FsListing => ({
  ...l,
  truncated: l.truncated ?? false,
  entries: l.entries.map((e) => ({ size: null, ...e })),
})

function caseQuery(f: CaseFilter): Record<string, string> {
  const q: Record<string, string> = {}
  if (f.q?.trim()) q.q = f.q.trim()
  if (f.phase) q.phase = f.phase
  if (f.status) q.status = f.status
  if (f.voi) q.has_voi = String(f.voi === 'any')
  for (const [name, v] of Object.entries(f.vars ?? {})) if (v) q[`var.${name}`] = v
  return q
}

// ---- API-40: one EventSource per project, shared by all subscribers ---------------------------
const EVENT_TYPES: ServerEvent['event'][] = ['curation.appended', 'job.progress', 'job.finished', 'index.rebuilt', 'project.updated']
interface Stream {
  es: EventSource
  listeners: Set<(e: ServerEvent) => void>
  states: Set<(s: ConnectionState) => void>
  state: ConnectionState
}
const streams = new Map<string, Stream>()

function openStream(pid: string): Stream {
  // EventSource reconnects on its own and resends Last-Event-ID, so the server replays what we missed
  const es = new EventSource(`${V1}/projects/${enc(pid)}/events`)
  const s: Stream = { es, listeners: new Set(), states: new Set(), state: 'connecting' }
  const setState = (st: ConnectionState) => {
    s.state = st
    for (const l of s.states) l(st)
  }
  es.onopen = () => setState('live')
  es.onerror = () => setState(es.readyState === EventSource.CLOSED ? 'offline' : 'connecting')
  for (const type of EVENT_TYPES)
    es.addEventListener(type, (m: MessageEvent<string>) => {
      let data: unknown
      try {
        data = JSON.parse(m.data)
      } catch {
        return
      }
      const e = { event: type, data } as ServerEvent
      for (const l of s.listeners) l(e)
    })
  return s
}

// ---- surface -------------------------------------------------------------------------------------
const SESSION_ID = Math.random().toString(36).slice(2, 10)

export const httpApi: Api = {
  mode: 'http',
  sessionId: SESSION_ID,

  subscribe(pid, listener, onState) {
    const s = streams.get(pid) ?? openStream(pid)
    streams.set(pid, s)
    s.listeners.add(listener)
    if (onState) {
      s.states.add(onState)
      onState(s.state)
    }
    return () => {
      s.listeners.delete(listener)
      if (onState) s.states.delete(onState)
      if (s.listeners.size === 0 && s.states.size === 0) {
        s.es.close()
        streams.delete(pid)
      }
    }
  },

  health: () => unwrap(client.GET('/api/v1/health')),

  // API-02..05
  async listProjects() {
    const rows = await unwrap(client.GET('/api/v1/projects'))
    return rows as ProjectSummary[]
  },
  getProject: async (pid) => normalizeProject(await unwrap(client.GET('/api/v1/projects/{pid}', { params: { path: { pid } } }))),
  createProject({ name, description = '', preset }) {
    // `preset` (PRJ-12) is added to ProjectCreate by lane/2-backend; older servers ignore it
    const body: { name: string; description: string; preset: Preset } = { name, description, preset }
    return unwrap(client.POST('/api/v1/projects', { body })).then(normalizeProject)
  },
  updateLabelMap: (pid, label_map) =>
    unwrap(client.PATCH('/api/v1/projects/{pid}', { params: { path: { pid } }, body: { label_map } })).then(normalizeProject),
  listRoots: (pid) => unwrap(client.GET('/api/v1/projects/{pid}/roots', { params: { path: { pid } } })),
  relinkRoot: (pid, alias, path) =>
    unwrap(client.PUT('/api/v1/projects/{pid}/roots/{alias}', { params: { path: { pid, alias } }, body: { path } })),

  // API-10..14
  fsList: (path) => unwrap(client.GET('/api/v1/fs/list', { params: { query: path ? { path } : {} } })).then(normalizeFs),
  importPreview(pid, req) {
    if (!req.files) return send('POST', `/projects/${enc(pid)}/imports/preview`, { root: req.root, alias: req.alias, detect: true })
    const fd = new FormData()
    fd.set('root', req.root)
    fd.set('alias', req.alias)
    fd.set('metadata', req.files.metadata)
    if (req.files.phase) fd.set('phase', req.files.phase)
    if (req.files.voi_catalog) fd.set('voi_catalog', req.files.voi_catalog)
    return send('POST', `/projects/${enc(pid)}/imports/preview`, fd)
  },
  commitImport: (pid, preview_id) =>
    unwrap(client.POST('/api/v1/projects/{pid}/imports', { params: { path: { pid } }, body: { preview_id } })),
  importHistory: (pid) => unwrap(client.GET('/api/v1/projects/{pid}/imports', { params: { path: { pid } } })),
  async listWarnings(pid) {
    const out: QCWarning[] = []
    let cursor: string | undefined
    do {
      const page = await unwrap(
        client.GET('/api/v1/projects/{pid}/warnings', { params: { path: { pid }, query: { limit: PAGE, cursor } } }),
      )
      out.push(...page.items.map(normalizeWarning))
      cursor = page.next_cursor ?? undefined
    } while (cursor)
    return out
  },

  // API-16..18 (lane/2-backend)
  async listVariables(pid) {
    try {
      return catalogToVariables(await send<Catalog>('GET', `/projects/${enc(pid)}/variables`))
    } catch (e) {
      if (e instanceof ProblemError && (e.status === 404 || e.status === 405)) return []
      throw e
    }
  },
  patchVariable: async (pid, name, patch) =>
    variableFrom(await send<Catalog>('PATCH', `/projects/${enc(pid)}/variables/${enc(name)}`, patch), name),
  createDerived: async (pid, def) =>
    variableFrom(await send<Catalog>('POST', `/projects/${enc(pid)}/variables/derived`, toWireDerived(def)), def.name),
  async deleteDerived(pid, name) {
    await send('DELETE', `/projects/${enc(pid)}/variables/derived/${enc(name)}`)
  },
  importExternal(pid, file, key) {
    const fd = new FormData()
    fd.set('file', file)
    fd.set('key', key)
    return send<ExternalReport>('POST', `/projects/${enc(pid)}/variables/external`, fd).then((r) => externalResult(r, key))
  },

  // API-20..26
  async listCases(pid, f = {}) {
    const out: CaseSummary[] = []
    let cursor: string | undefined
    const query = caseQuery(f)
    do {
      const page = await send<{ items: RawCase[]; next_cursor: string | null }>(
        'GET',
        `/projects/${enc(pid)}/cases?${new URLSearchParams({ ...query, limit: String(f.limit ?? PAGE), ...(cursor ? { cursor } : {}) })}`,
      )
      out.push(...page.items.map(normalizeCase))
      cursor = f.limit ? undefined : (page.next_cursor ?? undefined)
    } while (cursor)
    // The server filters `warning` by QC code; "any/none" is applied here
    if (f.warning === 'any') return out.filter((c) => c.n_warnings > 0)
    if (f.warning === 'none') return out.filter((c) => c.n_warnings === 0)
    return out
  },
  async getCase(pid, cid): Promise<CaseDetail> {
    const d = await unwrap(client.GET('/api/v1/projects/{pid}/cases/{cid}', { params: { path: { pid, cid } } }))
    return { summary: normalizeCase(d.case), items: d.scans.flatMap((s) => s.items.map(normalizeItem)), warnings: d.warnings.map(normalizeWarning) }
  },
  async getItem(pid, iid) {
    const d = await unwrap(client.GET('/api/v1/projects/{pid}/items/{iid}', { params: { path: { pid, iid } } }))
    const image_path = d.advanced.image_path ?? null
    const mask_path = d.advanced.mask_path ?? null
    return { ...normalizeItem(d), advanced: { image_path, mask_path, image_abs: image_path, mask_abs: mask_path }, warnings: (d.warnings ?? []).map(normalizeWarning) }
  },
  thumbnailUrl: (pid, iid) => `${V1}/projects/${enc(pid)}/items/${enc(iid)}/thumbnail`,

  // API-50..52 (P4 backend)
  listEvents(pid, f = {}) {
    const q = new URLSearchParams(Object.entries(f).filter((e): e is [string, string] => !!e[1]))
    return listOrEmpty(`/projects/${enc(pid)}/curation/events?${q}`)
  },
  appendEvent: (pid, ev, reviewer) => send('POST', `/projects/${enc(pid)}/curation/events`, { ...ev, session_id: SESSION_ID }, reviewerHeader(reviewer)),
  curationState: (pid) => listOrEmpty(`/projects/${enc(pid)}/curation/state`),
  queue: (pid) => listOrEmpty(`/projects/${enc(pid)}/curation/queue?format=json`),

  // API-30..37 (P5 backend)
  schema: () => send('GET', '/radiomics/schema'),
  validate: (settings, selection) => send('POST', '/radiomics/validate', { settings, selection }),
  estimate: (pid, selection) => send('POST', `/projects/${enc(pid)}/radiomics/estimate`, { selection }),
  listProfiles: (pid) => listOrEmpty(`/projects/${enc(pid)}/radiomics/profiles`),
  saveProfile: (pid, name, settings) => send('POST', `/projects/${enc(pid)}/radiomics/profiles`, { name, settings }),
  listRuns: (pid) => listOrEmpty(`/projects/${enc(pid)}/radiomics/runs`),
  getRun: (pid, rid) => send('GET', `/projects/${enc(pid)}/radiomics/runs/${enc(rid)}`),
  startRun: (pid, name, selection, reviewer) =>
    send('POST', `/projects/${enc(pid)}/radiomics/runs`, { name, selection }, reviewerHeader(reviewer)),
  runFeatures: (pid, rid, itemId) =>
    listOrEmpty(`/projects/${enc(pid)}/radiomics/runs/${enc(rid)}/features?format=json&shape=long${itemId ? `&item_id=${enc(itemId)}` : ''}`),
  runErrors: (pid, rid) => listOrEmpty(`/projects/${enc(pid)}/radiomics/runs/${enc(rid)}/errors`),

  // API-41
  listJobs: async (pid) => (await unwrap(client.GET('/api/v1/jobs', { params: { query: pid ? { project: pid } : {} } }))).map(normalizeJob),
  async cancelJob(_pid, jobId) {
    await unwrap(client.POST('/api/v1/jobs/{job_id}/cancel', { params: { path: { job_id: jobId } } }))
  },

  reset() {},
  setReviewerSimulation() {},
}
