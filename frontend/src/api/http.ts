// HTTP binding of the API surface (backend/API.md). Most endpoints go through the typed
// openapi-fetch client (FE-03); a few use `send` on the documented paths (multipart, the
// variables catalog).
import createClient from 'openapi-fetch'

import { ProblemError, toProblemError } from './problem'
import type { paths } from './schema'
import { viewPath } from './view'
import { filterByItems, type Api, type CaseFilter, type ConnectionState } from './surface'
import type {
  BundleImportResult,
  CurationEvent,
  CurationStateRow,
  DerivedDef,
  FeatureRow,
  ExternalImportResult,
  CaseDetail,
  CaseSummary,
  FsListing,
  ItemRecord,
  Job,
  Project,
  ProjectSummary,
  QCWarning,
  ServerEvent,
  V2ImportReport,
  Variable,
} from './types'

/** API base URL; empty = same origin (FE-07: configurable for Electron) */
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
const V1 = `${BASE}/api/v1`
const PAGE = 2000


// `fetch` is looked up per call (like `send`), so tests can stub it after this module loads
const client = createClient<paths>({
  baseUrl: BASE,
  fetch: (req) => {
    const url = viewPath(req.url)
    return globalThis.fetch(url === req.url ? req : new Request(url, req))
  },
})

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
  const r = await fetch(viewPath(`${V1}${path}`), init)
  const json: unknown = r.status === 204 ? null : await r.json().catch(() => null)
  if (!r.ok) throw toProblemError(r.status, json, r.statusText)
  return json as T
}

/** Every page of a cursor-paged list (API §Pagination) */
async function allPages<T>(get: (cursor: string | undefined) => Promise<{ items: T[]; next_cursor?: string | null }>): Promise<T[]> {
  const out: T[] = []
  let cursor: string | undefined
  do {
    const page = await get(cursor)
    out.push(...page.items)
    cursor = page.next_cursor ?? undefined
  } while (cursor)
  return out
}

const enc = encodeURIComponent

/** `Content-Disposition` file name (RFC 6266: `filename*=UTF-8''…` wins over `filename=`) */
export function attachmentName(header: string | null): string | null {
  if (!header) return null
  const star = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header)
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim())
    } catch {
      // malformed escape: fall back to the plain parameter
    }
  }
  const plain = /filename\s*=\s*"([^"]*)"|filename\s*=\s*([^;]+)/.exec(header)
  return (plain?.[1] ?? plain?.[2])?.trim() || null
}
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
  modality: null,
  image: null,
  masks: {},
  mask: null,
  geometry: null,
  labels_present: [],
  warning_codes: [],
  extra: {},
  ...i,
})

type Schemas = import('./schema').components['schemas']

export const DEFAULT_DISPLAY: Project['display'] = {
  layout: 'four-up',
  wl: { CT: { ww: 400, wl: 50 }, MR: 'percentile' },
  use_dicom_window: true,
  wl_presets: null,
  interpolation: 'linear',
  convention: 'radiological',
}

const normalizeProject = (p: Schemas['ProjectDetail']): Project => ({
  path_roots: [],
  phase_vocabulary: [],
  phase_priority: [],
  segmentations: [],
  annotation_sources: {},
  packs: [],
  view_token: null,
  view_url: null,
  ...p,
  display: { ...DEFAULT_DISPLAY, ...p.display },
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

/** `top` holds the most frequent values of every field; the UI shows them as levels only for these */
const LEVEL_TYPES = new Set<Variable['type']>(['categorical', 'numeric-discrete', 'constant'])

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
        levels: LEVEL_TYPES.has(v.type) ? (p.top ?? []).map((x) => ({ value: x.value, count: x.n })) : [],
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

const externalResult = (r: ExternalReport): ExternalImportResult => ({
  key: r.table.key,
  n_rows: r.n_rows,
  matched: r.n_matched,
  unmatched_keys: r.unmatched_keys ?? [],
  duplicate_keys: r.duplicate_keys ?? [],
  conflicts: r.conflicts ?? [],
  added: (r.table.columns ?? []).filter((c) => !(r.conflicts ?? []).includes(c)),
})

const normalizeWarning = (w: Schemas['QcWarning']): QCWarning => ({ case_id: null, field: null, item_id: null, path_ref: null, seg_id: null, ...w })

const normalizeJob = (j: Schemas['JobInfo']): Job => ({
  eta_s: null,
  started_at: null,
  finished_at: null,
  ref: null,
  error: null,
  key: null,
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

// ---- curation (API-50..54) -------------------------------------------------------------------
/** API-51 → one row per (item_id, target); case targets have `item_id = null` */
function stateRows(st: Schemas['CurationState']): CurationStateRow[] {
  const row = (item_id: string | null, case_id: string, x: Schemas['TargetState']): CurationStateRow => ({
    item_id,
    case_id,
    target: x.target,
    status: x.status,
    priority: x.priority,
    comment: x.comment,
    reviewer: x.reviewer,
    at: x.at,
    event_id: x.event_id,
    add_to_queue: x.add_to_queue ?? false,
    proposed_phase: x.proposed_phase ?? null,
    proposed_side: x.proposed_side ?? null,
  })
  return [
    ...st.items.flatMap((i) => i.targets.map((x) => row(i.item_id, i.case_id, x))),
    ...st.cases.flatMap((c) => (c.targets ?? []).map((x) => row(null, c.case_id, x))),
  ]
}

const normalizeEvent = (e: Schemas['CurationEvent']): CurationEvent => ({
  ...e,
  schema_version: 1,
  session_id: e.session_id ?? null,
  item_id: e.item_id ?? null,
  priority: e.priority ?? 'medium',
  comment: e.comment ?? '',
  proposed_phase: e.proposed_phase ?? null,
  proposed_side: e.proposed_side ?? null,
  add_to_queue: e.add_to_queue ?? false,
  source: e.source ?? 'ui',
  seg_id: e.seg_id ?? null,
  context: (e.context ?? {}) as CurationEvent['context'],
})

// ---- radiomics features (API-36) --------------------------------------------------------------
type Cell = string | number | null | undefined
const str = (v: Cell) => (v == null ? '' : String(v))
const num = (v: Cell) => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/** Long `FeaturesTable` rows → FeatureRow; `feature` becomes the full column name API-38 uses */
function featureRows(t: Schemas['FeaturesTable']): FeatureRow[] {
  return t.rows.map((r) => {
    const imageType = str(r.image_type) || 'original'
    const cls = str(r.feature_class)
    const name = str(r.feature)
    const status = str(r.ibsi_status)
    return {
      item_id: str(r.item_id),
      case_id: str(r.case_id),
      scan_idx: str(r.scan_idx),
      scope: str(r.scope) as FeatureRow['scope'],
      side: str(r.side) as FeatureRow['side'],
      phase: str(r.phase),
      label: Number(r.label),
      image_type: imageType,
      feature_class: cls,
      feature: `${imageType}_${cls}_${name}`,
      value: num(r.value),
      ibsi_code: r.ibsi_code == null ? null : str(r.ibsi_code),
      ibsi_status: status === 'compliant' || status === 'deviates' || status === 'not_defined' ? status : null,
    }
  })
}

async function blob(path: string, init: RequestInit = {}): Promise<Blob> {
  const r = await fetch(viewPath(`${V1}${path}`), init)
  if (!r.ok) throw toProblemError(r.status, await r.json().catch(() => null), r.statusText)
  return r.blob()
}

// ---- API-40: one EventSource per project, shared by all subscribers ---------------------------
const EVENT_TYPES: ServerEvent['event'][] = ['curation.appended', 'job.progress', 'job.finished', 'job.status', 'index.rebuilt', 'project.updated']
interface Stream {
  es: EventSource
  listeners: Set<(e: ServerEvent) => void>
  states: Set<(s: ConnectionState) => void>
  state: ConnectionState
}
const streams = new Map<string, Stream>()

function openStream(pid: string): Stream {
  // EventSource reconnects on its own and resends Last-Event-ID, so the server replays what we missed
  const es = new EventSource(viewPath(`${V1}/projects/${enc(pid)}/events`))
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
  createProject({ name, description = '', default_modality = 'CT' }) {
    return unwrap(client.POST('/api/v1/projects', { body: { name, description, default_modality } })).then(normalizeProject)
  },
  updateProject: (pid, body, etag) =>
    unwrap(client.PATCH('/api/v1/projects/{pid}', { params: { path: { pid }, header: { 'If-Match': etag } }, body })).then(normalizeProject),
  updateLabelMap: (pid, label_map, etag) =>
    unwrap(client.PATCH('/api/v1/projects/{pid}', { params: { path: { pid }, header: { 'If-Match': etag } }, body: { label_map } })).then(normalizeProject),
  listPacks: () => unwrap(client.GET('/api/v1/packs')),
  applyPack: (pid, pack_id) =>
    unwrap(client.POST('/api/v1/projects/{pid}/packs', { params: { path: { pid } }, body: { pack_id } })).then((r) => ({ ...r, project: normalizeProject(r.project) })),
  createViewToken: (pid) => unwrap(client.POST('/api/v1/projects/{pid}/view-token', { params: { path: { pid } } })),
  revokeViewToken: async (pid) => {
    await unwrap(client.DELETE('/api/v1/projects/{pid}/view-token', { params: { path: { pid } } }))
  },
  listRoots: (pid) => unwrap(client.GET('/api/v1/projects/{pid}/roots', { params: { path: { pid } } })),
  relinkRoot: (pid, alias, path) =>
    unwrap(client.PUT('/api/v1/projects/{pid}/roots/{alias}', { params: { path: { pid, alias } }, body: { path } })),
  setDerivedRoot: (pid, path, alias = 'DERIVED') =>
    unwrap(client.PUT('/api/v1/projects/{pid}/roots/{alias}', { params: { path: { pid, alias } }, body: { path, role: 'derived' } })),
  setDefaultSeg: (pid, default_seg, etag) =>
    unwrap(client.PATCH('/api/v1/projects/{pid}', { params: { path: { pid }, header: { 'If-Match': etag } }, body: { default_seg } })).then(normalizeProject),
  async exportBundle(pid) {
    const r = await fetch(`${V1}/projects/${enc(pid)}/bundle`, { method: 'POST' })
    if (!r.ok) throw toProblemError(r.status, await r.json().catch(() => null), r.statusText)
    return { blob: await r.blob(), filename: attachmentName(r.headers.get('content-disposition')) ?? `${pid}.zip` }
  },
  importBundle(file) {
    const fd = new FormData()
    fd.set('bundle', file)
    return send<BundleImportResult>('POST', '/projects/import-bundle', fd)
  },

  // API-10..14
  fsList: (path, role = 'source') =>
    unwrap(client.GET('/api/v1/fs/list', { params: { query: { ...(path ? { path } : {}), role } } })).then(normalizeFs),
  detectSource: (path) => unwrap(client.POST('/api/v1/sources/detect', { body: { path } })),
  openPath: (path) => unwrap(client.POST('/api/v1/open', { body: { path } })),
  getOpen: (sid) => unwrap(client.GET('/api/v1/open/{sid}', { params: { path: { sid } } })),
  async closeOpen(sid) {
    await send('DELETE', `/open/${enc(sid)}`)
  },
  openImageUrl: (sid, n, axisOrder) => `${V1}/open/${enc(sid)}/items/${n}/image${axisOrder ? `?axis_order=${axisOrder}` : ''}`,
  openPreviewUrl: (sid, n, axisOrder) => `${V1}/open/${enc(sid)}/items/${n}/preview?axis_order=${axisOrder}`,
  saveOpen: (sid, n, body) => unwrap(client.POST('/api/v1/open/{sid}/items/{n}/save', { params: { path: { sid, n } }, body })),
  attachOpen: (sid, n, path) => unwrap(client.POST('/api/v1/open/{sid}/items/{n}/attach', { params: { path: { sid, n } }, body: { path } })),
  importPreview(pid, req) {
    if (!req.files)
      return send('POST', `/projects/${enc(pid)}/imports/preview`, { root: req.root, alias: req.alias, detect: true, adapter: req.adapter, options: req.options ?? {}, add: req.add ?? false })
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
  startHashJob: (pid, force = false) =>
    unwrap(client.POST('/api/v1/projects/{pid}/hash-jobs', { params: { path: { pid } }, body: { force } })),
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
    return send<ExternalReport>('POST', `/projects/${enc(pid)}/variables/external`, fd).then(externalResult)
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
    // The server filters `warning` by QC code; "any/none" and the item list are applied here
    const byItems = filterByItems(out, f.itemIds)
    if (f.warning === 'any') return byItems.filter((c) => c.n_warnings > 0)
    if (f.warning === 'none') return byItems.filter((c) => c.n_warnings === 0)
    return byItems
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
  thumbnailUrl: (pid, iid) => viewPath(`${V1}/projects/${enc(pid)}/items/${enc(iid)}/thumbnail`),

  // API-50..54
  async listEvents(pid, f = {}) {
    const out: CurationEvent[] = []
    let cursor: string | undefined
    do {
      const page = await unwrap(
        client.GET('/api/v1/projects/{pid}/curation/events', { params: { path: { pid }, query: { ...f, limit: PAGE, cursor } } }),
      )
      out.push(...page.items.map(normalizeEvent))
      cursor = page.next_cursor ?? undefined
    } while (cursor)
    // The server pages in append order; CUR-14 shows newest first
    return out.sort((a, b) => b.at.localeCompare(a.at) || b.event_id.localeCompare(a.event_id))
  },
  appendEvent: async (pid, ev, reviewer) =>
    normalizeEvent(
      await unwrap(
        client.POST('/api/v1/projects/{pid}/curation/events', {
          params: { path: { pid }, header: { 'x-reviewer': reviewer, 'x-session-id': SESSION_ID } },
          body: { ...ev, context: { ...ev.context }, session_id: SESSION_ID, source: 'ui' },
        }),
      ),
    ),
  curationState: async (pid) => stateRows(await unwrap(client.GET('/api/v1/projects/{pid}/curation/state', { params: { path: { pid } } }))),
  queue: async (pid) =>
    ((await unwrap(client.GET('/api/v1/projects/{pid}/curation/queue', { params: { path: { pid }, query: { format: 'json' } } }))) as Schemas['QueueRow'][]).map((r) => ({
      scope: null,
      side: null,
      phase: null,
      image_path_abs: null,
      mask_path_abs: null,
      ...r,
    })),
  queueCsv: (pid) => blob(`/projects/${enc(pid)}/curation/queue?format=csv`),
  curationExports: (pid) => unwrap(client.POST('/api/v1/projects/{pid}/curation/exports', { params: { path: { pid } } })),
  importV2(pid, file, reviewer) {
    const fd = new FormData()
    fd.set('file', file)
    return send('POST', `/projects/${enc(pid)}/curation/import-v2`, fd, reviewerHeader(reviewer))
  },

  // API-30..37
  radiomicsSchema: () => unwrap(client.GET('/api/v1/radiomics/schema')),
  validateRadiomics: (settings, labels, nItems) =>
    unwrap(client.POST('/api/v1/radiomics/validate', { body: { settings, labels, n_items: nItems } })),
  listProfiles: (pid) =>
    allPages((cursor) => unwrap(client.GET('/api/v1/projects/{pid}/radiomics/profiles', { params: { path: { pid }, query: { limit: PAGE, cursor } } }))),
  saveProfile: (pid, name, settings) =>
    unwrap(client.POST('/api/v1/projects/{pid}/radiomics/profiles', { params: { path: { pid } }, body: { name, settings } })),
  renameProfile: (pid, phash, name) =>
    unwrap(client.PATCH('/api/v1/projects/{pid}/radiomics/profiles/{phash}', { params: { path: { pid, phash } }, body: { name } })),
  deleteProfile: async (pid, phash) =>
    (await unwrap(client.DELETE('/api/v1/projects/{pid}/radiomics/profiles/{phash}', { params: { path: { pid, phash }, query: { limit: PAGE } } }))).items,
  estimate: (pid, settings, selection) =>
    unwrap(client.POST('/api/v1/projects/{pid}/radiomics/estimate', { params: { path: { pid } }, body: { settings, selection } })),
  listRuns: (pid) =>
    allPages((cursor) => unwrap(client.GET('/api/v1/projects/{pid}/radiomics/runs', { params: { path: { pid }, query: { limit: PAGE, cursor } } }))),
  getRun: (pid, rid) => unwrap(client.GET('/api/v1/projects/{pid}/radiomics/runs/{rid}', { params: { path: { pid, rid } } })),
  startRun: (pid, body, reviewer) =>
    unwrap(client.POST('/api/v1/projects/{pid}/radiomics/runs', { params: { path: { pid }, header: { 'x-reviewer': reviewer } }, body })),
  cancelRun: (pid, rid) => unwrap(client.POST('/api/v1/projects/{pid}/radiomics/runs/{rid}/cancel', { params: { path: { pid, rid } } })),
  resumeRun: (pid, rid) => unwrap(client.POST('/api/v1/projects/{pid}/radiomics/runs/{rid}/resume', { params: { path: { pid, rid } } })),
  runFeatures: async (pid, rid, itemId) =>
    featureRows(
      await unwrap(
        client.GET('/api/v1/projects/{pid}/radiomics/runs/{rid}/features', {
          params: { path: { pid, rid }, query: { format: 'json', shape: 'long', ...(itemId ? { item_id: itemId } : {}) } },
        }),
      ) as Schemas['FeaturesTable'],
    ),
  runExportUrl: (pid, rid, format, shape) => viewPath(`${V1}/projects/${enc(pid)}/radiomics/runs/${enc(rid)}/features?format=${format}&shape=${shape}`),
  runErrors: (pid, rid) =>
    allPages((cursor) =>
      unwrap(client.GET('/api/v1/projects/{pid}/radiomics/runs/{rid}/errors', { params: { path: { pid, rid }, query: { limit: PAGE, cursor } } })),
    ),

  // API-38/39
  dashboardView: (pid, rid, view, body) => send('POST', `/projects/${enc(pid)}/radiomics/runs/${enc(rid)}/views/${view}`, body),
  async listAnalyses(pid, rid) {
    const r = await unwrap(client.GET('/api/v1/projects/{pid}/analyses', { params: { path: { pid }, query: rid ? { run_id: rid } : {} } }))
    return r.items
  },
  getAnalysis: (pid, aid) => unwrap(client.GET('/api/v1/projects/{pid}/analyses/{aid}', { params: { path: { pid, aid } } })),
  createAnalysis: (pid, spec, reviewer) =>
    unwrap(client.POST('/api/v1/projects/{pid}/analyses', { params: { path: { pid }, header: { 'x-reviewer': reviewer } }, body: spec })),
  exportAnalysis: (pid, aid, file) => blob(`/projects/${enc(pid)}/analyses/${enc(aid)}/export?file=${file}`),

  // API-24/27
  listSegmentations: (pid) => unwrap(client.GET('/api/v1/projects/{pid}/segmentations', { params: { path: { pid } } })),
  patchSegmentation: (pid, seg, body) =>
    unwrap(client.PATCH('/api/v1/projects/{pid}/segmentations/{seg}', { params: { path: { pid, seg } }, body })),
  maskUrl: (pid, iid, seg) => viewPath(`${V1}/projects/${enc(pid)}/items/${enc(iid)}/mask${seg ? `?seg=${enc(seg)}` : ''}`),

  // API-42..47
  listPlugins: (pid) => unwrap(client.GET('/api/v1/plugins', { params: { query: pid ? { project: pid } : {} } })),
  listTasks: () => unwrap(client.GET('/api/v1/tasks')),
  getTask: (tid) => unwrap(client.GET('/api/v1/tasks/{tid}', { params: { path: { tid } } })),
  validateTask: (tid, settings) => unwrap(client.POST('/api/v1/tasks/{tid}/validate', { params: { path: { tid } }, body: { settings } })),
  preflightTask: (pid, tid, selection, settings = {}) =>
    unwrap(client.POST('/api/v1/projects/{pid}/tasks/{tid}/preflight', { params: { path: { pid, tid } }, body: { selection, settings } })),
  estimateTask: (pid, tid, selection, settings = {}) =>
    unwrap(client.POST('/api/v1/projects/{pid}/tasks/{tid}/estimate', { params: { path: { pid, tid } }, body: { selection, settings } })),
  startTaskRun: (pid, body, reviewer) =>
    unwrap(
      client.POST('/api/v1/projects/{pid}/task-runs', {
        params: { path: { pid }, header: reviewer ? { 'X-Reviewer': reviewer } : {} },
        body,
      }),
    ),
  listTaskRuns: (pid, task) =>
    unwrap(client.GET('/api/v1/projects/{pid}/task-runs', { params: { path: { pid }, query: task ? { task } : {} } })),
  getTaskRun: (pid, rid) => unwrap(client.GET('/api/v1/projects/{pid}/task-runs/{rid}', { params: { path: { pid, rid } } })),
  cancelTaskRun: (pid, rid) => unwrap(client.POST('/api/v1/projects/{pid}/task-runs/{rid}/cancel', { params: { path: { pid, rid } } })),
  resumeTaskRun: (pid, rid) => unwrap(client.POST('/api/v1/projects/{pid}/task-runs/{rid}/resume', { params: { path: { pid, rid } } })),
  taskRunErrors: (pid, rid) => unwrap(client.GET('/api/v1/projects/{pid}/task-runs/{rid}/errors', { params: { path: { pid, rid } } })),
  taskRunOutputs: (pid, rid) => unwrap(client.GET('/api/v1/projects/{pid}/task-runs/{rid}/outputs', { params: { path: { pid, rid } } })),

  listAnnotations: (pid, f = {}) => unwrap(client.GET('/api/v1/projects/{pid}/annotations', { params: { path: { pid }, query: f } })),
  setAnnotationSource: (pid, field, run_id) =>
    unwrap(client.PUT('/api/v1/projects/{pid}/annotation-sources/{field}', { params: { path: { pid, field } }, body: { run_id } })),
  dicomTags: (pid, iid) => unwrap(client.GET('/api/v1/projects/{pid}/items/{iid}/dicom-tags', { params: { path: { pid, iid } } })),
  importConverterCuration(pid, file, reviewer) {
    const fd = new FormData()
    fd.set('file', file)
    return send<V2ImportReport>('POST', `/projects/${enc(pid)}/curation/import-converter`, fd, reviewerHeader(reviewer))
  },

  // API-41
  listJobs: async (pid) => (await unwrap(client.GET('/api/v1/jobs', { params: { query: pid ? { project: pid } : {} } }))).map(normalizeJob),
  async cancelJob(_pid, jobId) {
    await unwrap(client.POST('/api/v1/jobs/{job_id}/cancel', { params: { path: { job_id: jobId } } }))
  },

  reset() {},
  setReviewerSimulation() {},
}
