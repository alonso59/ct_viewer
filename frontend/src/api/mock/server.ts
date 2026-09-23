// In-memory mock of the HTTP API (backend/API.md) for the P0.5 prototype. No network.
// Seeded from `make fixtures` output via `npm run mock:seed`. Curation events persist in
// localStorage so a reload keeps the demo state; Settings → "Reset mock data" clears it.
import seedJson from './seed.json'
import { defaultSettings, MOCK_SCHEMA, validateSettings } from './schema'
import {
  QUEUE_STATUSES,
  STATUS_SEVERITY,
  type CaseDetail,
  type CaseSummary,
  type CurationEvent,
  type CurationStateRow,
  type CurationStatus,
  type FeatureRow,
  type FeatureValue,
  type FsEntry,
  type ImportPreview,
  type ItemRecord,
  type Job,
  type LabelDef,
  type NewCurationEvent,
  type Phase,
  type Project,
  type QCWarning,
  type RadiomicsRun,
  type RunError,
  type ServerEvent,
  type Settings,
} from '../types'

interface Seed {
  items: ItemRecord[]
  warnings: QCWarning[]
  runs: RadiomicsRun[]
  features: Record<string, FeatureValue[]>
  errors: Record<string, RunError[]>
}
const seed = seedJson as unknown as Seed

export const DEMO_PID = '01JSYNTH900PROJECT00000000'
const OFFLINE_PID = '01JDATASET820PROJECT000000'
const LS_EVENTS = 'rw.mock.events.v1'
const LS_EXTRA = 'rw.mock.projects.v1'

const LABELS: LabelDef[] = [
  { value: 1, name: 'kidney', color: '#00FFFF', opacity: 0.15, visible: true },
  { value: 2, name: 'tumor', color: '#FFFF00', opacity: 0.2, visible: true },
  { value: 3, name: 'cyst', color: '#FF00FF', opacity: 0.15, visible: false },
]

// ---- helpers -------------------------------------------------------------
let ulidCounter = 0
function ulid(): string {
  const t = Date.now().toString(36).toUpperCase().padStart(10, '0')
  ulidCounter = (ulidCounter + 1) % 1_000_000
  const r = Math.random().toString(36).slice(2, 12).toUpperCase().padEnd(10, '0')
  return `01${t}${r}${ulidCounter.toString(36).toUpperCase().padStart(4, '0')}`.slice(0, 26)
}
const wait = (ms = 140) => new Promise((r) => setTimeout(r, ms + Math.random() * 80))
const clone = <T>(v: T): T => structuredClone(v)
function readLs<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    return v ? (JSON.parse(v) as T) : fallback
  } catch {
    return fallback
  }
}
function writeLs(key: string, v: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(v))
  } catch {
    // storage unavailable (private mode): demo state is session-only
  }
}

export class ProblemError extends Error {
  constructor(
    public status: number,
    public type: string,
    public title: string,
    public detail?: string,
  ) {
    super(title)
  }
}

// ---- seeded curation history (design data) -------------------------------
function seededEvents(): CurationEvent[] {
  const base = (
    at: string,
    reviewer: string,
    item_id: string | null,
    target: string,
    status: CurationStatus,
    extra: Partial<CurationEvent> = {},
  ): CurationEvent => ({
    event_id: `01JSEED${at.replace(/\D/g, '').slice(0, 12)}${item_id?.slice(5, 10) ?? 'CASE0'}`.padEnd(26, '0').slice(0, 26),
    schema_version: 1,
    at,
    reviewer,
    session_id: 'seed',
    item_id,
    case_id: (item_id ?? extra.case_id ?? '').split('.')[0] ?? '',
    target,
    status,
    priority: 'medium',
    comment: '',
    proposed_phase: null,
    proposed_side: null,
    add_to_queue: false,
    context: {},
    source: 'ui',
    ...extra,
  })
  return [
    base('2026-09-22T09:12:00Z', 'Dr. AP', 'case_00001.01.complete.-', 'seg', 'accepted'),
    base('2026-09-22T09:14:00Z', 'Dr. AP', 'case_00001.02.complete.-', 'seg', 'accepted'),
    base('2026-09-22T09:17:00Z', 'Dr. AP', 'case_00001.03.complete.-', 'seg', 'accepted'),
    base('2026-09-22T09:25:00Z', 'Dr. AP', 'case_00002.01.complete.-', 'seg', 'accepted'),
    base('2026-09-22T09:31:00Z', 'Dr. AP', 'case_00002.03.complete.-', 'label:2', 'needs_minor_correction', {
      comment: 'Tumor boundary leaks into renal sinus on slices 20–26',
      context: { viewer: { axis: 'axial', slice: 24, ww: 400, wl: 50 } },
    }),
    base('2026-09-22T10:02:00Z', 'Dr. MK', 'case_00003.01.complete.-', 'seg', 'accepted'),
    base('2026-09-22T10:40:00Z', 'Dr. MK', 'case_00014.01.complete.-', 'label:2', 'needs_major_correction', {
      priority: 'high',
      comment: 'Tumor under-segmented; lower pole missing',
      add_to_queue: true,
    }),
    base('2026-09-23T08:05:00Z', 'Dr. AP', 'case_00016.01.complete.-', 'seg', 'rejected', {
      priority: 'high',
      comment: 'Mask shifted ~10 mm against the image',
    }),
    base('2026-09-23T08:20:00Z', 'Dr. AP', 'case_00018.01.complete.-', 'phase', 'wrong_phase_suspected', {
      comment: 'Renal medulla enhanced; looks nephrographic',
      proposed_phase: 'NP',
    }),
  ]
}

// ---- state -----------------------------------------------------------------
interface ProjectState {
  project: Project
  items: ItemRecord[]
  warnings: QCWarning[]
  runs: RadiomicsRun[]
  features: Record<string, FeatureValue[]>
  errors: Record<string, RunError[]>
  profiles: { name: string; hash: string; settings: Settings; saved_at: string }[]
}

const db = new Map<string, ProjectState>()
let events: Record<string, CurationEvent[]> = {}
const jobs = new Map<string, Job>()
type Listener = (e: ServerEvent) => void
const listeners = new Map<string, Set<Listener>>()

function emit(pid: string, e: ServerEvent) {
  for (const l of listeners.get(pid) ?? []) l(e)
}

function makeProject(pid: string, name: string, withData: boolean): ProjectState {
  const items = withData ? clone(seed.items) : []
  const cases = new Set(items.map((i) => i.case_id))
  return {
    project: {
      project_id: pid,
      name,
      created_at: '2026-09-21T15:00:00Z',
      last_opened_at: new Date().toISOString(),
      n_cases: cases.size,
      n_items: items.length,
      progress: { reviewed: 0, total: cases.size },
      roots: [{ alias: 'DATA', path: '/data/Dataset900', reachable: true }],
      label_map: clone(LABELS),
      share_url: `${location.origin}/p/${pid}`,
    },
    items,
    warnings: withData ? clone(seed.warnings) : [],
    runs: withData ? clone(seed.runs) : [],
    features: withData ? clone(seed.features) : {},
    errors: withData ? clone(seed.errors) : {},
    profiles: withData
      ? [{ name: 'Engine defaults', hash: 'sha256:9f2c…e41a', settings: defaultSettings(), saved_at: '2026-09-22T08:00:00Z' }]
      : [],
  }
}

function init() {
  db.clear()
  db.set(DEMO_PID, makeProject(DEMO_PID, 'Dataset900 (synthetic)', true))
  const offline = makeProject(OFFLINE_PID, 'ccRCC Dataset820', false)
  offline.project.n_cases = 820
  offline.project.n_items = 3104
  offline.project.progress = { reviewed: 412, total: 820 }
  offline.project.last_opened_at = '2026-09-19T17:40:00Z'
  offline.project.roots = [{ alias: 'DATA', path: '/mnt/nas/ccRCC/Dataset820', reachable: false }]
  db.set(OFFLINE_PID, offline)
  for (const p of readLs<{ pid: string; name: string; imported: boolean }[]>(LS_EXTRA, [])) {
    db.set(p.pid, makeProject(p.pid, p.name, p.imported))
  }
  events = readLs<Record<string, CurationEvent[]>>(LS_EVENTS, { [DEMO_PID]: seededEvents() })
}
init()

function persistExtraProjects() {
  writeLs(
    LS_EXTRA,
    [...db.values()]
      .filter((s) => s.project.project_id !== DEMO_PID && s.project.project_id !== OFFLINE_PID)
      .map((s) => ({ pid: s.project.project_id, name: s.project.name, imported: s.items.length > 0 })),
  )
}

function state(pid: string): ProjectState {
  const s = db.get(pid)
  if (!s) throw new ProblemError(404, 'not-found', 'Project not found', pid)
  if (!s.project.roots.every((r) => r.reachable))
    throw new ProblemError(409, 'source-missing', 'Data root not reachable', `Alias DATA → ${s.project.roots[0]?.path ?? ''}`)
  return s
}

// ---- curation reducer (CUR-08) --------------------------------------------
function latestState(pid: string): Map<string, CurationEvent> {
  const latest = new Map<string, CurationEvent>()
  for (const e of events[pid] ?? []) latest.set(`${e.item_id ?? e.case_id}|${e.target}`, e)
  return latest
}
export function rollup(statuses: CurationStatus[]): CurationStatus {
  return statuses.reduce<CurationStatus>(
    (worst, s) => (STATUS_SEVERITY[s] > STATUS_SEVERITY[worst] ? s : worst),
    'not_reviewed',
  )
}

function summaries(pid: string): CaseSummary[] {
  const s = state(pid)
  const latest = [...latestState(pid).values()]
  const byCase = new Map<string, ItemRecord[]>()
  for (const it of s.items) byCase.set(it.case_id, [...(byCase.get(it.case_id) ?? []), it])
  return [...byCase.entries()].map(([case_id, items]) => {
    const evs = latest.filter((e) => e.case_id === case_id)
    const complete = items.filter((i) => i.scope === 'complete')
    const thumb =
      complete.find((i) => i.phase.canonical === 'NP' && i.status === 'active') ??
      complete.find((i) => i.status === 'active')
    return {
      case_id,
      patient_id: items[0]?.patient_id ?? '',
      group: items[0]?.group ?? '',
      phases: [...new Set(complete.map((i) => i.phase.canonical))] as Phase[],
      n_scans: complete.length,
      n_items: items.length,
      has_seg: complete.some((i) => i.mask),
      has_voi_L: items.some((i) => i.scope === 'voi' && i.side === 'L'),
      has_voi_R: items.some((i) => i.scope === 'voi' && i.side === 'R'),
      n_warnings: s.warnings.filter((w) => w.case_id === case_id).length,
      curation_status: rollup(evs.map((e) => e.status)),
      last_reviewed_at: evs.map((e) => e.at).sort().at(-1) ?? null,
      thumb_item_id: thumb?.item_id ?? null,
      excluded: items.every((i) => i.status === 'excluded_upstream'),
    }
  })
}

export interface CaseFilter {
  q?: string
  group?: string
  phase?: string
  status?: string
  warning?: 'any' | 'none' | ''
  voi?: 'any' | 'none' | ''
  showExcluded?: boolean
}

// ---- simulated jobs ----------------------------------------------------------
function runJob(pid: string, job: Job, stepMs: number, onDone: () => void) {
  jobs.set(job.job_id, job)
  emit(pid, { event: 'job.progress', data: clone(job) })
  const timer = setInterval(() => {
    const j = jobs.get(job.job_id)
    if (!j || j.status !== 'running') {
      clearInterval(timer)
      return
    }
    j.done = Math.min(j.total, j.done + 1)
    j.eta_s = Math.round(((j.total - j.done) * stepMs) / 1000)
    if (j.done >= j.total) {
      clearInterval(timer)
      j.status = 'completed'
      j.eta_s = 0
      onDone()
      emit(pid, { event: 'job.finished', data: clone(j) })
    } else emit(pid, { event: 'job.progress', data: clone(j) })
  }, stepMs)
}

// ---- simulated second reviewer (CUR-11 demo) --------------------------------
let simTimer: ReturnType<typeof setInterval> | null = null
export function setReviewerSimulation(pid: string | null, on: boolean) {
  if (simTimer) clearInterval(simTimer)
  simTimer = null
  if (!pid || !on || !db.has(pid)) return
  const s = db.get(pid)
  if (!s || s.items.length === 0) return
  simTimer = setInterval(() => {
    const latest = latestState(pid)
    const candidates = s.items.filter(
      (i) => i.scope === 'complete' && i.status === 'active' && !latest.has(`${i.item_id}|seg`),
    )
    const it = candidates[Math.floor(Math.random() * candidates.length)]
    if (!it) return
    const status: CurationStatus = Math.random() < 0.75 ? 'accepted' : 'needs_minor_correction'
    appendEventSync(pid, {
      item_id: it.item_id, case_id: it.case_id, target: 'seg', status, priority: 'medium',
      comment: status === 'accepted' ? '' : 'Small leak at the upper pole', add_to_queue: false,
    }, 'Dr. MK', 'sim')
  }, 45_000)
}

function appendEventSync(pid: string, ev: NewCurationEvent, reviewer: string, session: string): CurationEvent {
  const full: CurationEvent = {
    event_id: ulid(),
    schema_version: 1,
    at: new Date().toISOString(),
    reviewer,
    session_id: session,
    proposed_phase: null,
    proposed_side: null,
    context: {},
    source: 'ui',
    ...ev,
  }
  events[pid] = [...(events[pid] ?? []), full]
  writeLs(LS_EVENTS, events)
  emit(pid, { event: 'curation.appended', data: full })
  return full
}

// ---- API surface -----------------------------------------------------------
const SESSION_ID = Math.random().toString(36).slice(2, 10)

export const mockServer = {
  sessionId: SESSION_ID,

  subscribe(pid: string, l: Listener): () => void {
    const set = listeners.get(pid) ?? new Set<Listener>()
    set.add(l)
    listeners.set(pid, set)
    return () => set.delete(l)
  },

  reset() {
    try {
      localStorage.removeItem(LS_EVENTS)
      localStorage.removeItem(LS_EXTRA)
    } catch {
      // ignore
    }
    init()
  },

  // API-02 / 03
  async listProjects(): Promise<Project[]> {
    await wait()
    return [...db.values()].map((s) => {
      const p = clone(s.project)
      if (s.items.length) {
        const sums = summaries(p.project_id)
        p.progress = { reviewed: sums.filter((c) => c.curation_status !== 'not_reviewed').length, total: sums.length }
      }
      return p
    })
  },
  async getProject(pid: string): Promise<Project> {
    await wait(60)
    const s = db.get(pid)
    if (!s) throw new ProblemError(404, 'not-found', 'Project not found', pid)
    s.project.last_opened_at = new Date().toISOString()
    return clone(s.project)
  },
  async createProject(name: string): Promise<Project> {
    await wait(250)
    const pid = ulid()
    db.set(pid, makeProject(pid, name, false))
    persistExtraProjects()
    return clone(db.get(pid)?.project as Project)
  },
  async updateLabelMap(pid: string, labels: LabelDef[]): Promise<Project> {
    await wait(80)
    const s = state(pid)
    s.project.label_map = clone(labels)
    emit(pid, { event: 'project.updated', data: { fields: ['label_map'] } })
    return clone(s.project)
  },

  // API-10 / 11 / 12
  async fsList(path: string): Promise<FsEntry[]> {
    await wait(90)
    const tree: Record<string, FsEntry[]> = {
      '/': [{ name: 'data', path: '/data', kind: 'dir' }],
      '/data': [
        { name: 'Dataset900', path: '/data/Dataset900', kind: 'dir', detected: ['metadata.jsonl', 'phase.json', 'voi/voi_catalog.jsonl'] },
        { name: 'Dataset820', path: '/data/Dataset820', kind: 'dir', detected: ['metadata.jsonl'] },
        { name: 'scratch', path: '/data/scratch', kind: 'dir' },
      ],
      '/data/Dataset900': [
        { name: 'nifti', path: '/data/Dataset900/nifti', kind: 'dir' },
        { name: 'seg', path: '/data/Dataset900/seg', kind: 'dir' },
        { name: 'voi', path: '/data/Dataset900/voi', kind: 'dir' },
        { name: 'metadata.jsonl', path: '/data/Dataset900/metadata.jsonl', kind: 'file' },
        { name: 'phase.json', path: '/data/Dataset900/phase.json', kind: 'file' },
      ],
    }
    return tree[path] ?? []
  },
  async importPreview(pid: string, root: string): Promise<ImportPreview> {
    await wait(600)
    db.get(pid)
    const cases = new Set(seed.items.map((i) => i.case_id))
    const errors = seed.warnings
      .filter((w) => w.severity === 'error')
      .map((w, i) => ({ row: i * 2 + 3, code: w.code, message: `${w.case_id}: ${w.message}` }))
    return {
      root,
      detected: [
        { file: 'metadata.jsonl', found: true, rows: 24 },
        { file: 'phase.json', found: true, rows: 1 },
        { file: 'voi/voi_catalog.jsonl', found: true, rows: 10 },
      ],
      n_rows: 24,
      n_cases: cases.size,
      n_items: seed.items.length,
      errors,
      mapping: [
        { field: 'case_id', source: 'case_id' },
        { field: 'scan_idx', source: 'scan_idx' },
        { field: 'image', source: 'relative_path' },
        { field: 'mask', source: 'seg/{filename} (convention)' },
        { field: 'phase', source: 'phase.json → phase' },
        { field: 'group', source: 'group' },
        { field: 'patient_id', source: 'patient_id' },
        { field: 'excluded', source: 'status, planned_conversion' },
      ],
    }
  },
  async commitImport(pid: string): Promise<{ job_id: string }> {
    await wait(200)
    const s = db.get(pid)
    if (!s) throw new ProblemError(404, 'not-found', 'Project not found')
    const job: Job = {
      job_id: ulid(), kind: 'indexing', title: 'Indexing Dataset900', status: 'running',
      done: 0, total: seed.items.length, eta_s: null, started_at: new Date().toISOString(), ref: null,
    }
    runJob(pid, job, 90, () => {
      const fresh = makeProject(pid, s.project.name, true)
      s.items = fresh.items
      s.warnings = fresh.warnings
      s.project.n_cases = new Set(s.items.map((i) => i.case_id)).size
      s.project.n_items = s.items.length
      persistExtraProjects()
      emit(pid, { event: 'index.rebuilt', data: { import_id: ulid(), n_items: s.items.length, n_warnings: s.warnings.length } })
    })
    return { job_id: job.job_id }
  },

  // API-14 / 20 / 21 / 22
  async listWarnings(pid: string): Promise<QCWarning[]> {
    await wait(80)
    return clone(state(pid).warnings)
  },
  async listCases(pid: string, f: CaseFilter = {}): Promise<CaseSummary[]> {
    await wait(100)
    const s = state(pid)
    const q = f.q?.trim().toLowerCase()
    return summaries(pid).filter((c) => {
      if (!f.showExcluded && c.excluded) return false
      if (q && !c.case_id.includes(q) && !c.patient_id.toLowerCase().includes(q)) return false
      if (f.group && c.group !== f.group) return false
      if (f.phase && !c.phases.includes(f.phase as Phase)) return false
      if (f.status && c.curation_status !== f.status) return false
      if (f.warning === 'any' && c.n_warnings === 0) return false
      if (f.warning === 'none' && c.n_warnings > 0) return false
      const hasVoi = s.items.some((i) => i.case_id === c.case_id && i.scope === 'voi')
      if (f.voi === 'any' && !hasVoi) return false
      if (f.voi === 'none' && hasVoi) return false
      return true
    })
  },
  async getCase(pid: string, cid: string): Promise<CaseDetail> {
    await wait(90)
    const s = state(pid)
    const summary = summaries(pid).find((c) => c.case_id === cid)
    if (!summary) throw new ProblemError(404, 'not-found', 'Case not found', cid)
    return {
      summary,
      items: clone(s.items.filter((i) => i.case_id === cid)),
      warnings: clone(s.warnings.filter((w) => w.case_id === cid)),
    }
  },
  async getItem(pid: string, iid: string): Promise<ItemRecord & { advanced: { image_abs: string | null; mask_abs: string | null } }> {
    await wait(60)
    const it = state(pid).items.find((i) => i.item_id === iid)
    if (!it) throw new ProblemError(404, 'not-found', 'Item not found', iid)
    const abs = (ref: string | undefined) => (ref ? ref.replace(/^DATA:/, '/data/Dataset900/') : null)
    return { ...clone(it), advanced: { image_abs: abs(it.image?.ref), mask_abs: abs(it.mask?.ref) } }
  },

  // API-50 / 51 / 52
  async listEvents(pid: string, f: { item_id?: string; case_id?: string } = {}): Promise<CurationEvent[]> {
    await wait(70)
    state(pid)
    return clone(
      (events[pid] ?? [])
        .filter((e) => (!f.item_id || e.item_id === f.item_id) && (!f.case_id || e.case_id === f.case_id))
        .reverse(),
    )
  },
  async appendEvent(pid: string, ev: NewCurationEvent, reviewer: string): Promise<CurationEvent> {
    await wait(90)
    if (!reviewer) throw new ProblemError(428, 'reviewer-required', 'Reviewer name required')
    state(pid)
    return appendEventSync(pid, ev, reviewer, SESSION_ID)
  },
  async curationState(pid: string): Promise<CurationStateRow[]> {
    await wait(70)
    state(pid)
    return [...latestState(pid).values()].map((e) => ({
      item_id: e.item_id, case_id: e.case_id, target: e.target, status: e.status, priority: e.priority,
      comment: e.comment, reviewer: e.reviewer, at: e.at, add_to_queue: e.add_to_queue,
    }))
  },
  async queue(pid: string): Promise<(CurationStateRow & { item: ItemRecord | null; image_abs: string | null; mask_abs: string | null })[]> {
    await wait(90)
    const s = state(pid)
    return [...latestState(pid).values()]
      .filter((e) => QUEUE_STATUSES.includes(e.status) || e.add_to_queue)
      .sort((a, b) => STATUS_SEVERITY[b.status] - STATUS_SEVERITY[a.status] || b.at.localeCompare(a.at))
      .map((e) => {
        const item = s.items.find((i) => i.item_id === e.item_id) ?? null
        return {
          item_id: e.item_id, case_id: e.case_id, target: e.target, status: e.status, priority: e.priority,
          comment: e.comment, reviewer: e.reviewer, at: e.at, add_to_queue: e.add_to_queue, item: clone(item),
          image_abs: item?.image ? item.image.ref.replace(/^DATA:/, '/data/Dataset900/') : null,
          mask_abs: item?.mask ? item.mask.ref.replace(/^DATA:/, '/data/Dataset900/') : null,
        }
      })
  },

  // API-30..38
  async schema() {
    await wait(120)
    return clone(MOCK_SCHEMA)
  },
  async validate(settings: Settings, selection: { labels: number[]; items: number }) {
    await wait(40)
    return validateSettings(settings, selection)
  },
  async estimate(pid: string, selection: { scope: string; labels: number[] }) {
    await wait(700)
    const n = state(pid).items.filter((i) => i.scope === selection.scope && i.status === 'active' && i.mask).length
    return { n_items: n, n_labels: selection.labels.length, n_extractions: n * selection.labels.length, sec_per_item: 2.4 }
  },
  async listProfiles(pid: string) {
    await wait(60)
    return clone(state(pid).profiles)
  },
  async saveProfile(pid: string, name: string, settings: Settings) {
    await wait(120)
    const s = state(pid)
    const hash = `sha256:${Math.abs(JSON.stringify(settings).split('').reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 7)).toString(16).padStart(8, '0')}…`
    s.profiles = [...s.profiles.filter((p) => p.name !== name), { name, hash, settings: clone(settings), saved_at: new Date().toISOString() }]
    return { name, hash }
  },
  async listRuns(pid: string): Promise<RadiomicsRun[]> {
    await wait(80)
    return clone(state(pid).runs).reverse()
  },
  async getRun(pid: string, rid: string): Promise<RadiomicsRun> {
    await wait(60)
    const r = state(pid).runs.find((x) => x.run_id === rid)
    if (!r) throw new ProblemError(404, 'not-found', 'Run not found', rid)
    return clone(r)
  },
  async startRun(pid: string, name: string, selection: { scope: 'complete' | 'voi'; labels: number[] }, reviewer: string) {
    await wait(200)
    const s = state(pid)
    const base = s.runs[0]
    const rid = ulid()
    const targets = s.items.filter((i) => i.scope === selection.scope && i.status === 'active' && i.mask)
    const run: RadiomicsRun = {
      run_id: rid, name, status: 'running', created_at: new Date().toISOString(), started_at: new Date().toISOString(),
      finished_at: null, reviewer, engine: MOCK_SCHEMA.engine, profile_hash: 'sha256:9f2c…e41a',
      selection: { ...selection, filter: 'status=active' },
      counts: { items: targets.length, ok: 0, failed: 0, features: 0 },
    }
    s.runs.push(run)
    const job: Job = {
      job_id: ulid(), kind: 'radiomics', title: `Radiomics · ${name}`, status: 'running', done: 0,
      total: Math.max(1, targets.length), eta_s: null, started_at: new Date().toISOString(), ref: rid,
    }
    runJob(pid, job, 350, () => {
      const src = base ? (s.features[base.run_id] ?? []) : []
      s.features[rid] = src
        .filter((f) => selection.labels.includes(f.label))
        .map((f) => ({ ...f, value: +(f.value * (0.98 + Math.random() * 0.04)).toFixed(4) }))
      s.errors[rid] = base ? clone(s.errors[base.run_id] ?? []) : []
      run.status = s.errors[rid].length ? 'completed_with_errors' : 'completed'
      run.finished_at = new Date().toISOString()
      run.counts = {
        items: targets.length,
        ok: targets.length - s.errors[rid].length,
        failed: s.errors[rid].length,
        features: new Set(s.features[rid].map((f) => f.feature)).size,
      }
    })
    return { run_id: rid, job_id: job.job_id }
  },
  async runFeatures(pid: string, rid: string, item_id?: string): Promise<FeatureRow[]> {
    await wait(90)
    const s = state(pid)
    const byId = new Map(s.items.map((i) => [i.item_id, i]))
    const all = s.features[rid] ?? []
    return (item_id ? all.filter((f) => f.item_id === item_id) : all).flatMap((f) => {
      const it = byId.get(f.item_id)
      return it
        ? [{ ...f, case_id: it.case_id, scan_idx: it.scan_idx, scope: it.scope, side: it.side, phase: it.phase.canonical, group: it.group }]
        : []
    })
  },
  async runErrors(pid: string, rid: string): Promise<RunError[]> {
    await wait(60)
    return clone(state(pid).errors[rid] ?? [])
  },

  // API-41
  async listJobs(): Promise<Job[]> {
    await wait(40)
    return clone([...jobs.values()]).reverse()
  },
  async cancelJob(pid: string, jobId: string) {
    await wait(60)
    const j = jobs.get(jobId)
    if (j && j.status === 'running') {
      j.status = 'cancelled'
      const run = db.get(pid)?.runs.find((r) => r.run_id === j.ref)
      if (run) run.status = 'cancelled'
      emit(pid, { event: 'job.finished', data: clone(j) })
    }
  },
}

export type MockServer = typeof mockServer
