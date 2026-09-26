// In-memory mock of the HTTP API (backend/API.md), bound with VITE_API_MODE=mock (standalone
// prototype, unit tests). No network. Seeded from `make fixtures` via `npm run mock:seed`; payloads
// follow the real shapes (types.ts). Curation events persist in localStorage so a reload keeps the
// demo state; Settings → "Reset mock data" clears it.
import { ProblemError } from '../problem'
import { MOCK_PLUGINS } from './plugins'
import { mockLabeling } from './labeling'
import { rollup } from '../rollup'
import { filterByItems, type Api, type CaseFilter } from '../surface'
import {
  QUEUE_STATUSES,
  STATUS_SEVERITY,
  type CaseSummary,
  type CurationEvent,
  type CurationStatus,
  type DerivedDef,
  type FeatureRow,
  type FsEntry,
  type ImportPreview,
  type ItemRecord,
  type Job,
  type LabelDef,
  type WorkspaceRun,
  type NewCurationEvent,
  type PhaseEvent,
  type Project,
  type ProjectSummary,
  type QCWarning,
  type QueueRow,
  type Profile,
  type RunDetail,
  type RunError,
  type ServerEvent,
  type SegmentationInfo,
  type TaskRunDetail,
  type TaskSelection,
  type Variable,
  type VariableValue,
} from '../types'
import { mockDashboardView } from './dashboard'
import { engineOf, loadEngine, profileHash, selectItems, toSummary } from './radiomics'
import seedJson from './seed.json'
import { MOCK_TASKS, preflight, validateSettings } from './tasks'
import { candidateFields, deriveValue, isMissing, parseTable, profileField, validateDerived, type Override, type Row } from './variables'

/** Seed feature value; `feature` is `{class}_{name}` */
interface FeatureValue {
  item_id: string
  label: number
  feature_class: string
  feature: string
  value: number
}
/** `npm run mock:seed` output: runs and errors in their pre-API-34 shapes, completed at load */
type SeedRun = Omit<RunDetail, 'engine' | 'ibsi_map_version' | 'settings' | 'inputs' | 'selection' | 'counts'> & {
  engine: { name: string; version: string }
  selection: Omit<RunDetail['selection'], 'item_ids'>
  counts: Omit<RunDetail['counts'], 'skipped'>
}
interface Seed {
  items: (Omit<ItemRecord, 'import_id' | 'phase'> & { phase: { canonical: ItemRecord['phase']['canonical']; raw: string } })[]
  warnings: (Omit<QCWarning, 'field' | 'path_ref'> & Partial<QCWarning>)[]
  runs: SeedRun[]
  features: Record<string, FeatureValue[]>
  errors: Record<string, Pick<RunError, 'item_id' | 'label' | 'error'>[]>
}
const seed = seedJson as unknown as Seed

const seedRuns = (): RunDetail[] =>
  seed.runs.map((r) => ({
    ...r,
    engine: { ...r.engine, deps: {} },
    ibsi_map_version: 'mock',
    settings: {},
    inputs: [],
    selection: { ...r.selection, item_ids: [] },
    counts: { ...r.counts, skipped: 0 },
    job_id: null,
  }))
const seedErrors = (): Record<string, RunError[]> =>
  Object.fromEntries(
    Object.entries(seed.errors).map(([rid, list]) => [
      rid,
      list.map((e) => ({ ...e, kind: 'failed' as const, at: seed.runs.find((r) => r.run_id === rid)?.finished_at ?? '2026-09-23T10:06:41Z' })),
    ]),
  )

export const DEMO_PID = '01JSYNTH900PROJECT00000000'
const OFFLINE_PID = '01JDATASET820PROJECT000000'
const LS_EVENTS = 'rw.mock.events.v1'
const LS_EXTRA = 'rw.mock.projects.v2'
const DEMO_ROOT = '/data/Dataset900'

const CCRCC_LABELS: LabelDef[] = [
  { value: 1, name: 'kidney', color: '#00FFFF', opacity: 0.15, visible: true },
  { value: 2, name: 'tumor', color: '#FFFF00', opacity: 0.2, visible: true },
  { value: 3, name: 'cyst', color: '#FF00FF', opacity: 0.15, visible: false },
]
/** PRJ-16 study packs (the shipped pack.json files, abridged) */
type PackId = 'ccrcc' | 'generic-ct'
const PACKS: Record<PackId, { title: string; labels: LabelDef[]; vocabulary: string[]; target: string }> = {
  ccrcc: { title: 'ccRCC (kidney CT)', labels: CCRCC_LABELS, vocabulary: ['NC', 'CMP', 'NP', 'EP', 'UNK'], target: 'kidneys' },
  'generic-ct': { title: 'Generic CT phases', labels: [], vocabulary: ['NC', 'ART', 'PV', 'DELAYED', 'UNK'], target: 'generic' },
}
const isPack = (id: string): id is PackId => id in PACKS
const workspaceRuns = new Map<string, WorkspaceRun>()
/** PRJ-15: the mock's ETag changes with every settings write */
let etagCounter = 0
const nextEtag = () => `"mock-${++etagCounter}"`
const AUTO_COLORS = ['#00FFFF', '#FFFF00', '#FF00FF', '#00FF00', '#FF8000', '#0080FF']

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
const now = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z')
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

/** Demo study variables per case (design data): the mock only knows them as raw metadata fields */
function demoFields(item: Seed['items'][number]): Record<string, unknown> {
  const n = Number(item.case_id.replace(/\D/g, '')) || 0
  const scan = Number(item.scan_idx) || 1
  const labelled = n % 3 !== 0
  const hb = labelled ? (n * 37) % 101 : ''
  return {
    hb,
    lb: labelled ? Math.max(0, 100 - Number(hb) - (n % 4)) : '',
    sn: labelled ? [0, 5, 7, 8, 10, 30][n % 6] : '',
    manufacturer: ['SIEMENS', 'Philips Medical Systems', 'GE MEDICAL SYSTEMS', 'Siemens Healthineers'][n % 4],
    kvp: [100, 120, 120, 140][(n + scan) % 4],
    scan_date: `2019${String((n % 12) + 1).padStart(2, '0')}${String((scan * 7) % 28 + 1).padStart(2, '0')}`,
    ...item.extra,
  }
}

/** Item modality (VW-05): the seed's own value, else its `extra.modality`, else CT */
function seedModality(i: Seed['items'][number]): string {
  const m = (i as { modality?: unknown }).modality ?? i.extra.modality
  return typeof m === 'string' && m.trim() ? m : 'CT'
}

function seedItems(importId: string): ItemRecord[] {
  return seed.items.map((i) => ({
    ...clone(i),
    modality: seedModality(i),
    masks: i.mask ? { imported: clone(i.mask) } : ({} as ItemRecord['masks']),
    import_id: importId,
    phase: { canonical: i.phase.canonical, raw: i.phase.raw, source: 'phase' },
    extra: demoFields(i),
  }))
}
const seedWarnings = (): QCWarning[] => seed.warnings.map((w) => ({ field: null, path_ref: null, ...clone(w) }))

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
    seg_id: target === 'seg' || target.startsWith('label:') ? 'imported' : null,
    item_id,
    case_id: (item_id ?? extra.case_id ?? '').split('.')[0] ?? '',
    target,
    status,
    priority: 'medium',
    comment: '',
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
  ]
}

// ---- state -----------------------------------------------------------------
interface ProjectState {
  project: Project
  last_opened_at: string | null
  /** PRJ-06: archived projects are listed only with `archived` and 404 elsewhere */
  archived?: boolean
  reachable: boolean
  items: ItemRecord[]
  warnings: QCWarning[]
  runs: RunDetail[]
  features: Record<string, FeatureValue[]>
  errors: Record<string, RunError[]>
  /** null until first read: the demo "Engine defaults" profile needs the lazily loaded schema */
  profiles: Profile[] | null
  overrides: Record<string, Override>
  derived: DerivedDef[]
  /** External table values by case_id (VAR-07) */
  external: Record<string, Record<string, string>>
  externalFields: string[]
  previews: Map<string, ImportPreview>
  imports: { import_id: string; at: string; preview: ImportPreview }[]
  taskRuns: TaskRunDetail[]
}

const db = new Map<string, ProjectState>()
let events: Record<string, CurationEvent[]> = {}
/** PHS-02: native phase selections per project, in append order */
const phaseEvents: Record<string, PhaseEvent[]> = {}
const jobs = new Map<string, Job>()
type Listener = (e: ServerEvent) => void
const listeners = new Map<string, Set<Listener>>()

function emit(pid: string, e: ServerEvent) {
  for (const l of listeners.get(pid) ?? []) l(e)
}

function makeProject(pid: string, name: string, packs: PackId[], withData: boolean): ProjectState {
  const d = packs[0] ? PACKS[packs[0]] : { labels: [], vocabulary: [] }
  const items = withData ? seedItems('01JSEEDIMPORT0000000000000') : []
  const ts = '2026-09-21T15:00:00Z'
  return {
    project: {
      format: 'radiology-workbench-project',
      format_version: 3,
      project_id: pid,
      name,
      description: '',
      created_at: ts,
      updated_at: ts,
      packs,
      default_modality: 'CT',
      view_token: null,
      view_url: null,
      read_only: false,
      etag: nextEtag(),
      path_roots: withData ? [{ alias: 'DATA', path: DEMO_ROOT, role: 'source' }] : [],
      label_map: clone(withData && d.labels.length === 0 ? autoLabels(items) : d.labels),
      phase_vocabulary: d.vocabulary,
      phase_mapping: {},
      phase_priority: d.vocabulary.length ? ['NP', 'CMP', 'NC', 'EP', 'UNK'] : ['UNK'],
      display: { layout: 'four-up', wl: { CT: { ww: 400, wl: 50 }, MR: 'percentile' }, use_dicom_window: true, wl_presets: null, interpolation: 'linear', convention: 'radiological' },
      segmentations: [{ seg_id: 'imported', name: '', kind: 'imported', producer: null, label_mapping: { '1': 1, '2': 2, '3': 3 }, unmatched: [], created_at: ts }],
      default_seg: 'imported',
      annotation_sources: {},
      share_url: `${location.origin}/p/${pid}`,
    },
    last_opened_at: withData ? now() : null,
    reachable: true,
    items,
    warnings: withData ? seedWarnings() : [],
    runs: withData ? seedRuns() : [],
    features: withData ? clone(seed.features) : {},
    errors: withData ? seedErrors() : {},
    profiles: withData ? null : [],
    overrides: {},
    derived: [],
    external: {},
    externalFields: [],
    previews: new Map(),
    imports: [],
    taskRuns: [],
  }
}

/** PRJ-07: without a preset label map, labels are auto-named from mask values */
function autoLabels(items: ItemRecord[]): LabelDef[] {
  const values = [...new Set(items.flatMap((i) => i.labels_present))].sort((a, b) => a - b)
  return values.map((value, k) => ({ value, name: `label_${value}`, color: AUTO_COLORS[k % AUTO_COLORS.length] ?? '#FFFFFF', opacity: 0.2, visible: true }))
}

interface Extra {
  pid: string
  name: string
  packs?: PackId[]
  imported: boolean
}

function init() {
  db.clear()
  db.set(DEMO_PID, makeProject(DEMO_PID, 'Dataset900 (synthetic)', ['ccrcc'], true))
  const offline = makeProject(OFFLINE_PID, 'ccRCC Dataset820', ['ccrcc'], false)
  offline.last_opened_at = '2026-09-19T17:40:00Z'
  offline.reachable = false
  offline.project.path_roots = [{ alias: 'DATA', path: '/mnt/nas/ccRCC/Dataset820', role: 'source' }]
  db.set(OFFLINE_PID, offline)
  for (const p of readLs<Extra[]>(LS_EXTRA, [])) db.set(p.pid, makeProject(p.pid, p.name, p.packs ?? [], p.imported))
  events = readLs<Record<string, CurationEvent[]>>(LS_EVENTS, { [DEMO_PID]: seededEvents() })
}
init()

function persistExtraProjects() {
  writeLs(
    LS_EXTRA,
    [...db.values()]
      .filter((s) => s.project.project_id !== DEMO_PID && s.project.project_id !== OFFLINE_PID)
      .map<Extra>((s) => ({ pid: s.project.project_id, name: s.project.name, packs: s.project.packs.filter(isPack), imported: s.items.length > 0 })),
  )
}

function checkEtag(s: ProjectState, etag: string) {
  if (etag !== s.project.etag && etag !== '*')
    throw new ProblemError(412, 'precondition-failed', 'Precondition failed', 'The project settings were changed by someone else: reload and reapply', ['reload'])
}

function exists(pid: string): ProjectState {
  const s = db.get(pid)
  if (!s || s.archived) throw new ProblemError(404, 'not-found', 'Project not found', pid)
  return s
}
function state(pid: string): ProjectState {
  const s = exists(pid)
  if (!s.reachable)
    throw new ProblemError(409, 'source-missing', 'Data root not reachable', `Alias DATA → ${s.project.path_roots[0]?.path ?? ''}`)
  return s
}

// ---- variables (VAR-*) ------------------------------------------------------------------------
const PHASE_EFFECTIVE = 'phase.effective'

function rows(s: ProjectState): Row[] {
  const base = s.items.map<Row>((i) => ({
    case_id: i.case_id,
    patient_id: i.patient_id,
    values: { ...i.extra, ...(s.external[i.case_id] ?? {}), [PHASE_EFFECTIVE]: i.phase.canonical },
  }))
  for (const def of s.derived) for (const r of base) r.values[def.name] = deriveValue(def, r.values, base)
  return base
}

function catalog(s: ProjectState, all = rows(s)): Variable[] {
  const external = new Set(s.externalFields)
  const derived = new Map(s.derived.map((d) => [d.name, d]))
  const metadata = candidateFields(all).filter((n) => !external.has(n) && !derived.has(n) && n !== PHASE_EFFECTIVE)
  return [
    ...metadata.map((n) => profileField(all, n, 'metadata', s.overrides[n])),
    profileField(all, PHASE_EFFECTIVE, 'layer', s.overrides[PHASE_EFFECTIVE]), // VAR-12 (ADR-0026)
    ...s.externalFields.map((n) => profileField(all, n, 'external', s.overrides[n])),
    ...[...derived.values()].map((d) => ({ ...profileField(all, d.name, 'derived', s.overrides[d.name]), definition: d })),
  ]
}

function matchesVar(v: unknown, spec: string): boolean {
  if (isMissing(v)) return false
  const range = /^(-?[\d.]*)\.\.(-?[\d.]*)$/.exec(spec)
  if (range) {
    const x = Number(v)
    return (range[1] === '' || x >= Number(range[1])) && (range[2] === '' || x <= Number(range[2]))
  }
  return String(v) === spec
}

// ---- cases (CUR-08 rollup) -------------------------------------------------------------------
function latestState(pid: string): Map<string, CurationEvent> {
  const latest = new Map<string, CurationEvent>()
  for (const e of events[pid] ?? []) latest.set(`${e.item_id ?? e.case_id}|${e.target}|${segOf(e) ?? ''}`, e)
  return latest
}

/** CURATION §Targets: mask targets carry a set; none = `imported` */
const segOf = (e: Pick<CurationEvent, 'target' | 'seg_id'>) =>
  e.target === 'seg' || e.target === 'voi_mask' || e.target.startsWith('label:') ? (e.seg_id ?? 'imported') : null

/** CUR-08 case rollup as the server computes it (AUD-A5-15): reviewed once every active item has a
 *  decision; partial with a non-queue worst status shows `partially_reviewed` */
function caseRollup(evs: CurationEvent[], items: ItemRecord[]): Pick<CaseSummary, 'curation_status' | 'review_state' | 'n_items_reviewed' | 'n_items_active'> {
  const worst = rollup(evs.map((e) => e.status))
  const active = items.filter((i) => i.status === 'active').map((i) => i.item_id)
  const decided = active.filter((id) => rollup(evs.filter((e) => e.item_id === id).map((e) => e.status)) !== 'not_reviewed').length
  const state = worst === 'not_reviewed' ? 'not_reviewed' : decided < active.length ? 'partial' : 'reviewed'
  return {
    curation_status: state === 'partial' && !QUEUE_STATUSES.includes(worst) ? 'partially_reviewed' : worst,
    review_state: state,
    n_items_reviewed: decided,
    n_items_active: active.length,
  }
}

function summaries(pid: string): CaseSummary[] {
  const s = state(pid)
  const latest = [...latestState(pid).values()]
  const all = rows(s)
  const caseVars = catalog(s, all).filter((v) => v.level === 'case' && v.visible)
  const byCase = new Map<string, { items: ItemRecord[]; rows: Row[] }>()
  s.items.forEach((it, k) => {
    const e = byCase.get(it.case_id) ?? { items: [], rows: [] }
    e.items.push(it)
    const r = all[k]
    if (r) e.rows.push(r)
    byCase.set(it.case_id, e)
  })
  return [...byCase.entries()].map(([case_id, { items, rows: rs }]) => {
    const evs = latest.filter((e) => e.case_id === case_id)
    const complete = items.filter((i) => i.scope === 'complete')
    const thumb =
      complete.find((i) => i.phase.canonical === 'NP' && i.status === 'active') ??
      complete.find((i) => i.status === 'active')
    const variables: Record<string, VariableValue> = {}
    for (const v of caseVars) {
      const raw = rs[0]?.values[v.name]
      variables[v.name] = isMissing(raw) ? null : v.type === 'continuous' ? Number(raw) : String(raw)
    }
    return {
      case_id,
      patient_id: items[0]?.patient_id ?? null,
      phases: [...new Set(complete.map((i) => i.phase.canonical))],
      n_scans: complete.length,
      n_items: items.length,
      has_seg: complete.some((i) => i.mask),
      has_voi_L: items.some((i) => i.scope === 'voi' && i.side === 'L'),
      has_voi_R: items.some((i) => i.scope === 'voi' && i.side === 'R'),
      n_warnings: s.warnings.filter((w) => w.case_id === case_id).length,
      ...caseRollup(evs, items),
      last_reviewed_at: evs.map((e) => e.at).sort().at(-1) ?? null,
      thumb_item_id: thumb?.item_id ?? null,
      excluded: items.every((i) => i.status === 'excluded_upstream'),
      variables,
    }
  })
}

// ---- simulated jobs ----------------------------------------------------------
function runJob(pid: string, job: Job, stepMs: number, onDone: () => void) {
  jobs.set(job.job_id, job)
  const progress = (j: Job) => emit(pid, { event: 'job.progress', data: { job_id: j.job_id, kind: j.kind, done: j.done, total: j.total, eta_s: j.eta_s } })
  progress(job)
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
      j.status = 'succeeded'
      j.eta_s = 0
      j.finished_at = now()
      onDone()
      progress(j)
      emit(pid, { event: 'job.finished', data: { job_id: j.job_id, kind: j.kind, status: j.status, ref: j.ref } })
    } else progress(j)
  }, stepMs)
}

function newJob(pid: string, kind: Job['kind'], total: number, ref: string | null): Job {
  const ts = now()
  return { job_id: ulid(), kind, project_id: pid, status: 'running', done: 0, total, eta_s: null, created_at: ts, started_at: ts, finished_at: null, ref, error: null, key: null }
}

// ---- simulated second reviewer (CUR-11 demo) --------------------------------
let simTimer: ReturnType<typeof setInterval> | null = null

function appendEventSync(pid: string, ev: NewCurationEvent, reviewer: string, session: string): CurationEvent {
  const full: CurationEvent = {
    event_id: ulid(),
    schema_version: 1,
    at: now(),
    reviewer,
    seg_id: ev.seg_id ?? (ev.target === 'seg' || ev.target === 'voi_mask' || ev.target.startsWith('label:') ? 'imported' : null),
    session_id: session,
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

const absPath = (ref: string | undefined) => (ref ? ref.replace(/^DATA:/, `${DEMO_ROOT}/`) : null)

// ---- mock file system (API-10) ------------------------------------------------------------------
const FS: Record<string, FsEntry[]> = {
  '/data': [
    { name: 'Dataset900', path: DEMO_ROOT, kind: 'dir', size: null, has_metadata: true },
    { name: 'Dataset820', path: '/data/Dataset820', kind: 'dir', size: null, has_metadata: true },
    { name: 'scratch', path: '/data/scratch', kind: 'dir', size: null, has_metadata: false },
  ],
  [DEMO_ROOT]: [
    { name: 'nifti', path: `${DEMO_ROOT}/nifti`, kind: 'dir', size: null, has_metadata: false },
    { name: 'seg', path: `${DEMO_ROOT}/seg`, kind: 'dir', size: null, has_metadata: false },
    { name: 'voi', path: `${DEMO_ROOT}/voi`, kind: 'dir', size: null, has_metadata: false },
    { name: 'metadata.jsonl', path: `${DEMO_ROOT}/metadata.jsonl`, kind: 'file', size: 18_204, has_metadata: false },
    { name: 'phase.json', path: `${DEMO_ROOT}/phase.json`, kind: 'file', size: 812, has_metadata: false },
  ],
}

function queueRows(pid: string): QueueRow[] {
  const s = state(pid)
  return [...latestState(pid).values()]
    .filter((e) => e.item_id && (QUEUE_STATUSES.includes(e.status) || e.add_to_queue))
    .sort((a, b) => STATUS_SEVERITY[b.status] - STATUS_SEVERITY[a.status] || b.at.localeCompare(a.at))
    .map((e) => {
      const item = s.items.find((i) => i.item_id === e.item_id)
      return {
        case_id: e.case_id, item_id: e.item_id ?? '', scope: item?.scope ?? null, side: item?.side ?? null,
        phase: item?.phase.canonical ?? null, target: e.target, seg_id: segOf(e), status: e.status, priority: e.priority,
        comment: e.comment, reviewer: e.reviewer, at: e.at,
        // AUD-A2-16: the mask of the decision's set
        image_path_abs: absPath(item?.image?.ref), mask_path_abs: absPath((segOf(e) ? item?.masks[segOf(e) ?? ''] : item?.mask)?.ref),
      }
    })
}

/** API-36 long rows; the seed stores `{class}_{name}`, the wire name adds the image type */
function featureRows(s: ProjectState, rid: string, itemId?: string): FeatureRow[] {
  const byId = new Map(s.items.map((i) => [i.item_id, i]))
  const all = s.features[rid] ?? []
  return (itemId ? all.filter((f) => f.item_id === itemId) : all).flatMap((f) => {
    const it = byId.get(f.item_id)
    const name = f.feature.startsWith(`${f.feature_class}_`) ? f.feature.slice(f.feature_class.length + 1) : f.feature
    return it
      ? [{
          item_id: f.item_id, case_id: it.case_id, scan_idx: it.scan_idx, scope: it.scope, side: it.side, phase: it.phase.canonical,
          label: f.label, image_type: 'original', feature_class: f.feature_class, feature: `original_${f.feature_class}_${name}`,
          value: Number.isFinite(f.value) ? f.value : null, ibsi_code: null, ibsi_status: null,
        }]
      : []
  })
}

// ---- radiomics (API-30..37) -------------------------------------------------------------------
async function profilesOf(s: ProjectState): Promise<Profile[]> {
  if (s.profiles) return s.profiles
  const e = await loadEngine()
  const settings = e.normalize(e.schema.defaults)
  const at = '2026-09-22T08:00:00Z'
  s.profiles ??= [{ profile_hash: profileHash(settings), name: 'Engine defaults', created_at: at, updated_at: at, engine: engineOf(e.schema), settings }]
  return s.profiles
}

/** Study variable value of an item for selection filters (metadata `extra` + external tables) */
const valueOf =
  (s: ProjectState) =>
  (i: ItemRecord, name: string): unknown =>
    s.external[i.case_id]?.[name] ?? i.extra[name]

function runOf(s: ProjectState, rid: string): RunDetail {
  const r = s.runs.find((x) => x.run_id === rid)
  if (!r) throw new ProblemError(404, 'not-found', 'Run not found', rid)
  return r
}

/** Simulated extraction: one job step per unit; values jittered from the seed run's features */
function execute(pid: string, s: ProjectState, run: RunDetail) {
  const base = s.runs.find((r) => r !== run && s.features[r.run_id]?.length)
  const ids = new Set(run.selection.item_ids)
  const labels = run.selection.labels
  const job = newJob(pid, 'radiomics', Math.max(1, ids.size * labels.length), run.run_id)
  run.job_id = job.job_id
  run.status = 'running'
  run.started_at = now()
  runJob(pid, job, 250, () => {
    const features = (base ? (s.features[base.run_id] ?? []) : [])
      .filter((f) => ids.has(f.item_id) && labels.includes(f.label))
      .map((f) => ({ ...f, value: +(f.value * (0.98 + Math.random() * 0.04)).toFixed(4) }))
    const errors = (base ? (s.errors[base.run_id] ?? []) : []).filter((e) => ids.has(e.item_id) && labels.includes(e.label))
    const failed = new Set(errors.map((e) => e.item_id)).size
    s.features[run.run_id] = features
    s.errors[run.run_id] = errors.map((e) => ({ ...e, at: now() }))
    run.status = errors.length ? 'completed_with_errors' : 'completed'
    run.finished_at = now()
    run.counts = { items: ids.size, ok: ids.size - failed, failed, features: new Set(features.map((f) => f.feature)).size, skipped: 0 }
  })
}

/** API-36 CSV, long (one row per value) or wide (one row per item × label) */
function featuresCsv(rows: FeatureRow[], shape: 'long' | 'wide'): string {
  const cell = (v: unknown) => (v == null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replaceAll('"', '""')}"` : String(v))
  const meta = ['item_id', 'case_id', 'scan_idx', 'scope', 'side', 'phase', 'label'] as const
  if (shape === 'long') {
    const cols = [...meta, 'image_type', 'feature_class', 'feature', 'value'] as const
    return [cols.join(','), ...rows.map((r) => cols.map((c) => cell(r[c])).join(','))].join('\n')
  }
  const features = [...new Set(rows.map((r) => r.feature))]
  const byUnit = new Map<string, FeatureRow[]>()
  for (const r of rows) {
    const k = `${r.item_id}|${r.label}`
    byUnit.set(k, [...(byUnit.get(k) ?? []), r])
  }
  const lines = [...byUnit.values()].map((list) => {
    const first = list[0] as FeatureRow
    const val = new Map(list.map((r) => [r.feature, r.value]))
    return [...meta.map((c) => cell(first[c])), ...features.map((f) => cell(val.get(f)))].join(',')
  })
  return [[...meta, ...features].join(','), ...lines].join('\n')
}

// ---- tasks (API-42..47) ------------------------------------------------------
function taskOf(tid: string) {
  const t = MOCK_TASKS.find((x) => x.manifest.id === tid)
  if (!t) throw new ProblemError(404, 'not-found', 'Task not found', tid)
  return t
}

function taskItems(s: ProjectState, sel: TaskSelection): ItemRecord[] {
  let items = s.items.filter((i) => i.status === 'active')
  if (sel.item_ids) {
    const wanted = new Set(sel.item_ids)
    items = items.filter((i) => wanted.has(i.item_id))
  }
  if (sel.filter?.phase?.length) items = items.filter((i) => sel.filter?.phase?.includes(i.phase.canonical))
  if (sel.scope) items = items.filter((i) => i.scope === sel.scope)
  return items
}

function taskRunOf(s: ProjectState, rid: string): TaskRunDetail {
  const r = s.taskRuns.find((x) => x.run_id === rid)
  if (!r) throw new ProblemError(404, 'not-found', 'Task run not found', rid)
  return r
}

/** A simulated segmentation run: the "masks" reuse the imported files (nothing is computed) */
function executeTask(pid: string, s: ProjectState, run: TaskRunDetail, ready: ItemRecord[]) {
  const job = newJob(pid, 'task', ready.length, run.run_id)
  run.job_id = job.job_id
  run.status = 'running'
  run.started_at = now()
  runJob(pid, job, 250, () => {
    const segId = (run.settings.seg_id as string | undefined) ?? `threshold-${run.run_id.slice(0, 8).toLowerCase()}`
    for (const it of ready) if (it.image) it.masks = { ...it.masks, [segId]: { ref: it.masks.imported?.ref ?? it.image.ref, format: 'nifti' } }
    s.project.segmentations = [
      ...s.project.segmentations,
      { seg_id: segId, name: run.name, kind: 'task', producer: { task_id: run.task.id, version: run.task.version, run_id: run.run_id, settings_hash: run.settings_hash }, label_mapping: { '1': 1 }, unmatched: [], created_at: now() },
    ]
    run.status = 'completed'
    run.finished_at = now()
    run.counts = { items: ready.length, failed: 0, skipped: run.counts?.skipped ?? 0, ok: ready.length }
    run.outputs = [{ kind: 'segmentation_set', seg_id: segId, item_id: null, ref: null, sha256: null, detail: null }]
    emit(pid, { event: 'project.updated', data: { fields: ['segmentations'] } })
  })
}

// ---- API surface -----------------------------------------------------------
const SESSION_ID = Math.random().toString(36).slice(2, 10)

export const mockServer: Api = {
  mode: 'mock',
  sessionId: SESSION_ID,

  subscribe(pid, l, onState) {
    const set = listeners.get(pid) ?? new Set<Listener>()
    set.add(l)
    listeners.set(pid, set)
    onState?.('live')
    return () => set.delete(l)
  },

  async health() {
    return { status: 'ok', version: 'mock', ui_config: { viewer_max_loaded: 3, public_base_url: location.origin } }
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

  setReviewerSimulation(pid, on) {
    if (simTimer) clearInterval(simTimer)
    simTimer = null
    if (!pid || !on || !db.has(pid)) return
    const s = db.get(pid)
    if (!s || s.items.length === 0) return
    simTimer = setInterval(() => {
      const latest = latestState(pid)
      const candidates = s.items.filter(
        (i) => i.scope === 'complete' && i.status === 'active' && !latest.has(`${i.item_id}|seg|imported`),
      )
      const it = candidates[Math.floor(Math.random() * candidates.length)]
      if (!it) return
      const status: CurationStatus = Math.random() < 0.75 ? 'accepted' : 'needs_minor_correction'
      appendEventSync(pid, {
        item_id: it.item_id, case_id: it.case_id, target: 'seg', status, priority: 'medium',
        comment: status === 'accepted' ? '' : 'Small leak at the upper pole', add_to_queue: false,
      }, 'Dr. MK', 'sim')
    }, 45_000)
  },

  // API-02..05
  async listProjects(opts = {}): Promise<ProjectSummary[]> {
    await wait()
    return [...db.values()].filter((s) => !!s.archived === !!opts.archived).map((s) => {
      const sums = s.reachable && !s.archived && s.items.length ? summaries(s.project.project_id) : []
      const reviewed = sums.filter((c) => c.review_state === 'reviewed').length
      return {
        project_id: s.project.project_id,
        name: s.project.name,
        created_at: s.project.created_at,
        last_opened_at: s.last_opened_at,
        archived: !!s.archived,
        n_cases: s.project.project_id === OFFLINE_PID ? 820 : sums.length,
        curation_progress: s.project.project_id === OFFLINE_PID ? 0.5 : sums.length ? reviewed / sums.length : 0,
        share_url: s.project.share_url,
      }
    })
  },
  async getProject(pid) {
    await wait(60)
    const s = exists(pid)
    s.last_opened_at = now()
    return clone(s.project)
  },
  async archiveProject(pid) {
    await wait(120)
    const s = exists(pid)
    // AUD-A5-10: same rule as the server (API-04)
    const busy = [...jobs.values()].find((j) => j.project_id === pid && (j.status === 'running' || j.status === 'queued'))
    if (busy) throw new ProblemError(409, 'job-conflict', 'Conflicting job', `A ${busy.kind} job is running (${busy.job_id}); wait for it or cancel it, then archive`)
    s.archived = true
    return (await this.listProjects({ archived: true })).find((p) => p.project_id === pid) as ProjectSummary
  },
  async unarchiveProject(pid) {
    await wait(120)
    const s = db.get(pid)
    if (!s?.archived) throw new ProblemError(404, 'not-found', 'Project not found', pid)
    s.archived = false
    return clone(s.project)
  },
  async createProject({ name, description = '', default_modality = 'CT' }) {
    await wait(250)
    const pid = ulid()
    const s = makeProject(pid, name, [], false)
    s.project.description = description
    s.project.default_modality = default_modality
    s.project.created_at = s.project.updated_at = now()
    db.set(pid, s)
    persistExtraProjects()
    return clone(s.project)
  },
  async updateProject(pid, patch, etag) {
    await wait(80)
    const s = exists(pid)
    checkEtag(s, etag)
    const fields = Object.keys(patch).filter((k) => patch[k as keyof typeof patch] != null)
    Object.assign(s.project, clone(Object.fromEntries(fields.map((k) => [k, patch[k as keyof typeof patch]]))))
    s.project.etag = nextEtag()
    s.project.updated_at = now()
    emit(pid, { event: 'project.updated', data: { fields } })
    if (fields.includes('name')) persistExtraProjects()
    return clone(s.project)
  },
  async updateLabelMap(pid, labels, etag) {
    return this.updateProject(pid, { label_map: labels }, etag)
  },
  async listPacks() {
    await wait(40)
    return Object.entries(PACKS).map(([pack_id, p]) => ({ pack_id, plugin: pack_id, title: p.title, description: '', labels: p.labels.map((l) => l.name), phase_vocabulary: p.vocabulary, target_profile: p.target }))
  },
  async applyPack(pid, packId) {
    await wait(120)
    const s = exists(pid)
    if (!isPack(packId)) throw new ProblemError(404, 'not-found', 'Study pack not found', packId)
    const p = PACKS[packId]
    const byValue = new Map(s.project.label_map.map((l) => [l.value, l]))
    for (const l of p.labels) byValue.set(l.value, clone(l))
    s.project.label_map = [...byValue.values()].sort((a, b) => a.value - b.value)
    s.project.phase_vocabulary = [...p.vocabulary]
    s.project.packs = [...s.project.packs.filter((x) => x !== packId), packId]
    s.project.etag = nextEtag()
    persistExtraProjects()
    emit(pid, { event: 'project.updated', data: { fields: ['packs', 'label_map', 'phase_vocabulary'] } })
    return { project: clone(s.project), job_id: null }
  },
  async createViewToken(pid) {
    await wait(60)
    const s = exists(pid)
    const token = Math.random().toString(36).slice(2).padEnd(20, 'x')
    s.project.view_token = token
    s.project.view_url = `${location.origin}/v/${token}`
    s.project.etag = nextEtag()
    return { view_token: token, view_url: s.project.view_url }
  },
  async revokeViewToken(pid) {
    await wait(60)
    const s = exists(pid)
    s.project.view_token = null
    s.project.view_url = null
    s.project.etag = nextEtag()
  },
  async listRoots(pid) {
    await wait(60)
    const s = exists(pid)
    return s.project.path_roots.map((r) => ({ ...r, exists: s.reachable }))
  },
  async relinkRoot(pid, alias, path) {
    await wait(700)
    const s = exists(pid)
    const clean = path.replace(/\/$/, '')
    const found = FS[clean] !== undefined
    // The demo "offline" project relinks to any existing mock folder
    if (found) {
      s.reachable = true
      s.project.path_roots = s.project.path_roots.map((r) => (r.alias === alias ? { ...r, path: clean } : r))
      if (!s.items.length && s.project.project_id === OFFLINE_PID) {
        s.items = seedItems('01JSEEDIMPORT0000000000000')
        s.warnings = seedWarnings()
      }
    }
    return {
      root: { alias, path: clean, exists: found, role: s.project.path_roots.find((r) => r.alias === alias)?.role ?? 'source' },
      verify: { sampled: found ? 20 : 0, matched: found ? 20 : 0, mismatched: 0, missing: found ? 0 : 20, samples: [] },
    }
  },

  // API-06: bundles need the project folder on a server
  async exportBundle(pid) {
    await wait(60)
    exists(pid)
    throw new ProblemError(503, 'server-busy', 'Not available in the mock', 'Project bundles need the backend (API-06)')
  },
  async importBundle() {
    await wait(60)
    throw new ProblemError(503, 'server-busy', 'Not available in the mock', 'Project bundles need the backend (API-06)')
  },

  // API-10..14
  async setDerivedRoot(pid, path, alias = 'DERIVED') {
    await wait(200)
    const s = exists(pid)
    s.project.path_roots = [...s.project.path_roots.filter((r) => r.role !== 'derived'), { alias, path, role: 'derived' }]
    return { root: { alias, path, exists: true, role: 'derived' }, verify: { sampled: 0, matched: 0, mismatched: 0, missing: 0, samples: [] } }
  },
  async setDefaultSeg(pid, segId, etag) {
    await wait(60)
    const s = exists(pid)
    checkEtag(s, etag)
    if (!s.project.segmentations.some((x) => x.seg_id === segId)) throw new ProblemError(422, 'validation', 'Unknown segmentation set', segId)
    s.project.default_seg = segId
    for (const it of s.items) it.mask = it.masks[segId] ?? null
    return clone(s.project)
  },
  async listSegmentations(pid) {
    await wait(60)
    const s = exists(pid)
    return s.project.segmentations.map((x): SegmentationInfo => ({ ...clone(x), n_items: s.items.filter((i) => x.seg_id in i.masks).length, is_default: x.seg_id === s.project.default_seg }))
  },
  async patchSegmentation(pid, segId, patch) {
    await wait(60)
    const s = exists(pid)
    const seg = s.project.segmentations.find((x) => x.seg_id === segId)
    if (!seg) throw new ProblemError(404, 'not-found', 'Segmentation set not found', segId)
    if (patch.name != null) seg.name = patch.name
    if (patch.label_mapping != null) seg.label_mapping = patch.label_mapping
    return { ...clone(seg), n_items: s.items.filter((i) => segId in i.masks).length, is_default: segId === s.project.default_seg }
  },
  maskUrl: () => null,
  async listPlugins() {
    await wait(40)
    return { plugins: clone(MOCK_PLUGINS), invalid: [] }
  },
  async estimateWorkspaceTask() {
    await wait(300)
    return { n_units: 2, n_skipped: 1, seconds_per_item: null, estimated_total_s: null, output_bytes: 2_400_000, basis: 'sample', sample_item_ids: [], sample_errors: [], detail: { series: 3, selected: 2, skipped: 1, nifti_gz_estimated_bytes: 2_400_000 } }
  },
  async startWorkspaceRun(body) {
    await wait(150)
    const rid = ulid()
    const name = (body.name ?? '').trim() || `dataset-${now().slice(0, 10)}` // never the source folder's name (NFR-17)
    const at = now()
    workspaceRuns.set(rid, {
      run_id: rid, task: { id: body.task_id, version: '1.1.0', manifest_hash: 'mock' }, plugin: 'dicom', name, status: 'completed', created_at: at, started_at: at, finished_at: at,
      source: body.selection.source ?? '', dataset_dir: `/mock/derived/_datasets/${name}`, settings: body.settings ?? {}, settings_hash: 'mock', counts: { series: 3, selected: 2, converted: 2 }, progress: { done: 3, total: 3 }, error: null, job_id: null,
    })
    return { run_id: rid, job_id: null, status: 'completed' as const }
  },
  async listWorkspaceRuns() {
    await wait(40)
    return clone([...workspaceRuns.values()])
  },
  async getWorkspaceRun(rid) {
    await wait(40)
    const r = workspaceRuns.get(rid)
    if (!r) throw new ProblemError(404, 'not-found', 'Workspace task run not found', rid)
    return clone(r)
  },
  async cancelWorkspaceRun(rid) {
    return this.getWorkspaceRun(rid)
  },
  async listLayers() {
    await wait(40)
    return []
  },
  datasetTableUrl: () => '#',
  async listLabelTables(pid, deleted = false) {
    await wait(40)
    return mockLabeling.list(pid, exists(pid).items, deleted)
  },
  async createLabelTable(pid, body) {
    await wait(60)
    exists(pid)
    return mockLabeling.create(pid, body)
  },
  async patchLabelTable(pid, tid, body) {
    await wait(60)
    return mockLabeling.patch(pid, tid, body)
  },
  async labelCells(pid, tid) {
    await wait(60)
    const items = mockLabeling.cells(pid, tid, exists(pid).items)
    return { items, next_cursor: null, total: items.length }
  },
  async writeLabelCells(pid, tid, cells, reviewer) {
    await wait(60)
    const events = mockLabeling.write(pid, tid, cells, reviewer, SESSION_ID)
    for (const e of events) emit(pid, { event: 'labeling.appended', data: e })
    return { n_events: events.length }
  },
  async labelHistory(pid, tid, target, col) {
    await wait(40)
    return mockLabeling.history(pid, tid, target, col)
  },
  async importLabelTable() {
    await wait(60)
    return { key: 'case_id', n_rows: 0, matched: 0, unmatched: [], columns: [], ignored_columns: [], n_events: 0, errors: [] }
  },
  labelExportUrl: () => '#',
  async listTasks() {
    await wait(60)
    return { tasks: clone(MOCK_TASKS), invalid: [], runners: [{ runner_id: 'mock-runner', tasks: ['segment.threshold'], gpu: null, pid: 1, at: now(), fresh: true }] }
  },
  async getTask(tid) {
    await wait(40)
    return clone(taskOf(tid))
  },
  async validateTask(tid, settings) {
    await wait(40)
    return validateSettings(taskOf(tid).manifest, settings)
  },
  async preflightTask(pid, tid, selection) {
    await wait(80)
    const s = exists(pid)
    return preflight(taskOf(tid).manifest, taskItems(s, selection), selection, s.project.default_seg, s.project.path_roots.some((r) => r.role === 'derived'))
  },
  async estimateTask(pid, tid, selection) {
    await wait(120)
    const s = exists(pid)
    const m = taskOf(tid).manifest
    const pre = preflight(m, taskItems(s, selection), selection, s.project.default_seg, true)
    const spi = m.resources?.seconds_per_item ?? null
    return { n_units: pre.n_ready, n_skipped: pre.n_selected - pre.n_ready, seconds_per_item: spi, estimated_total_s: spi == null ? null : spi * pre.n_ready, output_bytes: null, basis: spi == null ? 'unknown' : 'manifest', sample_item_ids: [], sample_errors: [] }
  },
  async startTaskRun(pid, body, reviewer) {
    await wait(150)
    const s = exists(pid)
    const t = taskOf(body.task_id)
    if (t.manifest.id === 'radiomics.pyradiomics') throw new ProblemError(422, 'validation', 'Use the radiomics settings tab in the mock', t.manifest.id)
    const v = validateSettings(t.manifest, body.settings ?? {})
    if (!v.ok || !v.settings) throw new ProblemError(422, 'validation', 'Invalid settings', v.issues.map((i) => i.msg).join('; '))
    if (!s.project.path_roots.some((r) => r.role === 'derived')) throw new ProblemError(409, 'derived-root-required', 'Choose a derived folder first', 'PRJ-13')
    const sel = body.selection ?? {}
    const items = taskItems(s, sel)
    const pre = preflight(t.manifest, items, sel, s.project.default_seg, true)
    const ready = items.filter((i) => (pre.ready_item_ids ?? []).includes(i.item_id))
    const ts = now()
    const run: TaskRunDetail = {
      run_id: ulid(), task: { id: t.manifest.id, version: t.manifest.version, manifest_hash: t.manifest_hash }, name: body.name ?? `${t.manifest.title} ${ts}`,
      status: 'queued', created_at: ts, started_at: null, finished_at: null, reviewer: reviewer ?? null, job_id: null,
      counts: { items: ready.length, ok: 0, failed: 0, skipped: items.length - ready.length }, error: null,
      runtime: t.manifest.runtime.type, settings: v.settings, settings_hash: v.settings_hash ?? '', selection: sel,
      item_ids: ready.map((i) => i.item_id), inputs: [], versions: {}, output_dir: null, outputs: [], attempts: 1, progress: null, detail_url: null,
    }
    s.taskRuns.push(run)
    executeTask(pid, s, run, ready)
    return { run_id: run.run_id, job_id: run.job_id ?? null, status: run.status }
  },
  async listTaskRuns(pid, tid) {
    await wait(60)
    const runs = state(pid).taskRuns.filter((r) => !tid || r.task.id === tid)
    return clone(runs).reverse()
  },
  async getTaskRun(pid, rid) {
    await wait(40)
    return clone(taskRunOf(state(pid), rid))
  },
  async cancelTaskRun(pid, rid) {
    await wait(60)
    const run = taskRunOf(state(pid), rid)
    const j = run.job_id ? jobs.get(run.job_id) : undefined
    if (j && j.status === 'running') j.status = 'cancelled'
    if (run.status === 'running' || run.status === 'queued') {
      run.status = 'cancelled'
      run.finished_at = now()
    }
    return clone(run)
  },
  async resumeTaskRun(pid, rid) {
    await wait(60)
    const run = taskRunOf(state(pid), rid)
    throw new ProblemError(409, 'job-conflict', 'Resume is not simulated in the mock', run.run_id)
  },
  async taskRunErrors() {
    await wait(40)
    return []
  },
  async taskRunOutputs(pid, rid) {
    await wait(40)
    return clone(taskRunOf(state(pid), rid).outputs ?? [])
  },
  async detectSource(path) {
    await wait(150)
    const counts = { nifti: 0, dicom: 0, npy: 0, ignored: 0 }
    if (path === DEMO_ROOT)
      return { path, kind: 'folder', root: path, candidates: [{ adapter: 'metadata-v1', reason: 'metadata.jsonl found (contract v1)', counts, confidence: 'high', options: {}, available: true, unavailable_reason: null }], counts, ignored: {}, truncated: false }
    throw new ProblemError(415, 'unsupported-format', 'No accepted file in the mock', 'The mock only knows the demo dataset', ['choose_another_path'])
  },
  async openDicomTags() {
    await wait(40)
    return {}
  },
  async openPath() {
    await wait(60)
    throw new ProblemError(503, 'server-busy', 'Not available in the mock', 'Open mode needs the backend (API-07)')
  },
  async getOpen(sid) {
    await wait(20)
    throw new ProblemError(404, 'not-found', 'Open session not found', sid)
  },
  async closeOpen() {},
  openImageUrl: () => null,
  openPreviewUrl: () => null,
  async saveOpen() {
    await wait(20)
    throw new ProblemError(503, 'server-busy', 'Not available in the mock', 'Open mode needs the backend (API-09)')
  },
  async listAnnotations() {
    await wait(40)
    return []
  },
  async setAnnotationSource(pid, field, runId) {
    await wait(40)
    const s = exists(pid)
    s.project.annotation_sources = { ...s.project.annotation_sources, [field]: runId }
    return { annotation_sources: clone(s.project.annotation_sources), job_id: null }
  },
  async dicomTags(_pid, iid) {
    await wait(20)
    throw new ProblemError(404, 'not-found', 'No DICOM sidecar in the mock', iid)
  },
  async importConverterCuration() {
    await wait(20)
    throw new ProblemError(503, 'server-busy', 'Not available in the mock', 'API-55 needs the backend')
  },
  async attachOpen() {
    await wait(20)
    throw new ProblemError(503, 'server-busy', 'Not available in the mock', 'Open mode needs the backend (API-08)')
  },
  async fsList(path) {
    await wait(90)
    if (!path) return { path: null, parent: null, entries: [{ name: '/data', path: '/data', kind: 'dir', size: null, has_metadata: false }], truncated: false }
    const parent = path === '/data' ? null : path.slice(0, path.lastIndexOf('/')) || null
    return { path, parent, entries: FS[path] ?? [], truncated: false }
  },
  async importPreview(pid, req) {
    await wait(600)
    const s = exists(pid)
    const cases = new Set(seed.items.map((i) => i.case_id))
    const errors = req.root === DEMO_ROOT || req.files ? [] : [{ file: 'metadata.jsonl', line: null, field: null, message: 'metadata.jsonl not found under the root' }]
    const preview: ImportPreview = {
      preview_id: ulid(),
      root: req.root,
      alias: req.alias,
      files: errors.length
        ? []
        : [
            { kind: 'metadata', name: req.files?.metadata.name ?? 'metadata.jsonl', source: req.files ? 'uploaded' : 'detected', sha256: 'cd77c5ad…', rows: 24 },
            { kind: 'phase', name: 'phase.json', source: 'detected', sha256: '634571c4…', rows: 1 },
            { kind: 'voi_catalog', name: 'voi_catalog.jsonl', source: 'detected', sha256: '2fed5d0f…', rows: 10 },
          ],
      counts: { scan_rows: errors.length ? 0 : 24, voi_rows: errors.length ? 0 : 10, cases: errors.length ? 0 : cases.size, excluded_upstream: errors.length ? 0 : 1 },
      errors,
      n_errors: errors.length,
      field_mapping: { image: 'relative_path', seg: 'convention', phase: ['phase.json', 'phase'], side: 'side' },
      adapter: req.adapter ?? 'metadata-v1',
      options: {},
      sample: [],
      unmatched: [],
      orphan_masks: [],
      ignored: {},
    }
    s.previews.set(preview.preview_id, preview)
    return preview
  },
  async commitImport(pid, previewId) {
    await wait(200)
    const s = exists(pid)
    const preview = s.previews.get(previewId)
    if (!preview) throw new ProblemError(404, 'not-found', 'Preview not found', previewId)
    const importId = ulid()
    const job = newJob(pid, 'index', seed.items.length, importId)
    runJob(pid, job, 60, () => {
      s.items = seedItems(importId)
      s.warnings = seedWarnings()
      s.project.path_roots = [{ alias: preview.alias, path: preview.root, role: 'source' }]
      if (s.project.label_map.length === 0) s.project.label_map = autoLabels(s.items)
      s.imports.push({ import_id: importId, at: now(), preview })
      persistExtraProjects()
      emit(pid, { event: 'index.rebuilt', data: { import_id: importId, n_items: s.items.length, n_warnings: s.warnings.length } })
    })
    return { job_id: job.job_id, import_id: importId }
  },
  async importHistory(pid) {
    await wait(60)
    const s = exists(pid)
    const last = s.imports.at(-1)
    return {
      items: s.imports.map((i) => ({ import_id: i.import_id, at: i.at, alias: i.preview.alias, root: i.preview.root, files: i.preview.files, counts: i.preview.counts, adapter: i.preview.adapter ?? 'metadata-v1' })).reverse(),
      next_cursor: null,
      total: s.imports.length,
      index: {
        state: s.items.length ? 'ready' : 'empty',
        import_id: last?.import_id ?? null,
        job_id: null,
        started_at: null,
        finished_at: last?.at ?? null,
        n_items: s.items.length,
        n_warnings: s.warnings.length,
        error: null,
      },
    }
  },
  async listWarnings(pid) {
    await wait(80)
    return clone(state(pid).warnings)
  },
  /** API-15: a simulated `hash` job over the image + mask files; nothing is hashed in the mock */
  async startHashJob(pid) {
    await wait(80)
    const s = state(pid)
    if ([...jobs.values()].some((j) => j.project_id === pid && j.kind === 'hash' && j.status === 'running'))
      throw new ProblemError(409, 'job-conflict', 'A hash job is already running', pid)
    const files = new Set(s.items.flatMap((i) => [i.image?.ref, i.mask?.ref]).filter(Boolean)).size
    const job = newJob(pid, 'hash', Math.max(1, files), null)
    runJob(pid, job, 40, () => undefined)
    return { job_id: job.job_id, n_files: files, n_skipped: 0 }
  },

  // API-16..18
  async listVariables(pid) {
    await wait(90)
    return catalog(state(pid))
  },
  async patchVariable(pid, name, patch) {
    await wait(80)
    const s = state(pid)
    if (!catalog(s).some((v) => v.name === name)) throw new ProblemError(404, 'not-found', 'Variable not found', name)
    s.overrides[name] = { ...s.overrides[name], ...patch }
    emit(pid, { event: 'project.updated', data: { fields: ['variables'] } })
    const v = catalog(s).find((x) => x.name === name)
    if (!v) throw new ProblemError(404, 'not-found', 'Variable not found', name)
    return v
  },
  async createDerived(pid, def) {
    await wait(120)
    const s = state(pid)
    const cat = catalog(s)
    const err = validateDerived(def, new Set(cat.map((v) => v.name)))
    if (err) throw new ProblemError(422, 'validation', 'Invalid derived variable', err)
    s.derived.push(clone(def))
    emit(pid, { event: 'project.updated', data: { fields: ['variables'] } })
    const v = catalog(s).find((x) => x.name === def.name)
    if (!v) throw new ProblemError(500, 'about:blank', 'Derived variable missing')
    return v
  },
  async brokenDerived(pid) {
    await wait(60)
    const s = state(pid)
    const names = new Set(catalog(s).map((v) => v.name))
    return s.derived.filter((d) => !names.has(d.name)).map((d) => ({ name: d.name, reason: `Unknown source variable ${JSON.stringify(d.op === 'dominant' ? d.sources.find((x) => !names.has(x)) : d.source)}` }))
  },
  async deleteDerived(pid, name) {
    await wait(80)
    const s = state(pid)
    if (s.derived.some((d) => d.op === 'dominant' ? d.sources.includes(name) : d.source === name))
      throw new ProblemError(409, 'conflict', 'Variable in use', `Another derived variable uses "${name}"`)
    s.derived = s.derived.filter((d) => d.name !== name)
    delete s.overrides[name]
    emit(pid, { event: 'project.updated', data: { fields: ['variables'] } })
  },
  async importExternal(pid, file, key) {
    await wait(300)
    const s = state(pid)
    const { header, rows: table } = parseTable(await file.text())
    const k = header.indexOf(key)
    if (k < 0) throw new ProblemError(422, 'validation', 'Key column missing', `The table has no "${key}" column`)
    const byKey = new Map<string, string>()
    for (const it of s.items) byKey.set(key === 'case_id' ? it.case_id : (it.patient_id ?? ''), it.case_id)
    // Same rules as the backend: columns whose name is taken are skipped; the first row per key wins
    const taken = new Set(catalog(s).filter((v) => v.source !== 'external').map((v) => v.name))
    const cols = header.filter((h, i) => i !== k && h !== '')
    const conflicts = cols.filter((c) => taken.has(c))
    const added = cols.filter((c) => !taken.has(c))
    const unmatched: string[] = []
    const seen = new Set<string>()
    const duplicates = new Set<string>()
    let matched = 0
    for (const r of table) {
      const rk = r[k] ?? ''
      if (seen.has(rk)) {
        duplicates.add(rk)
        continue
      }
      seen.add(rk)
      const cid = byKey.get(rk)
      if (!cid) {
        unmatched.push(rk)
        continue
      }
      matched++
      const vals = s.external[cid] ?? {}
      header.forEach((h, i) => {
        if (added.includes(h)) vals[h] = r[i] ?? ''
      })
      s.external[cid] = vals
    }
    s.externalFields = [...new Set([...s.externalFields, ...added])]
    emit(pid, { event: 'project.updated', data: { fields: ['variables'] } })
    return { key, n_rows: table.length, matched, unmatched_keys: unmatched, duplicate_keys: [...duplicates], conflicts, added }
  },

  // API-20..26
  async listCases(pid, f: CaseFilter = {}) {
    await wait(100)
    const s = state(pid)
    const all = rows(s)
    const q = f.q?.trim().toLowerCase()
    const vars = Object.entries(f.vars ?? {}).filter(([, v]) => v)
    const list = summaries(pid).filter((c) => {
      if (c.excluded && !f.showExcluded) return false
      if (q && !c.case_id.includes(q) && !(c.patient_id ?? '').toLowerCase().includes(q)) return false
      if (f.phase && !c.phases.includes(f.phase as CaseSummary['phases'][number])) return false
      if (f.status && c.curation_status !== f.status) return false // API-20 `curation_status`
      if (f.warning === 'any' && c.n_warnings === 0) return false
      if (f.warning === 'none' && c.n_warnings > 0) return false
      const hasVoi = c.has_voi_L || c.has_voi_R
      if (f.voi === 'any' && !hasVoi) return false
      if (f.voi === 'none' && hasVoi) return false
      // A case matches a variable filter when any of its items does (scan-level variables)
      for (const [name, spec] of vars)
        if (!all.some((r) => r.case_id === c.case_id && matchesVar(r.values[name], spec))) return false
      return true
    })
    const byItems = filterByItems(list, f.itemIds)
    return f.limit ? byItems.slice(0, f.limit) : byItems
  },
  async getCase(pid, cid) {
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
  async getItem(pid, iid) {
    await wait(60)
    const s = state(pid)
    const it = s.items.find((i) => i.item_id === iid)
    if (!it) throw new ProblemError(404, 'not-found', 'Item not found', iid)
    return {
      ...clone(it),
      advanced: {
        image_path: absPath(it.image?.ref),
        mask_path: absPath(it.mask?.ref),
        image_abs: absPath(it.image?.ref),
        mask_abs: absPath(it.mask?.ref),
      },
      warnings: clone(s.warnings.filter((w) => w.item_id === iid)),
    }
  },
  thumbnailUrl: () => null,

  // API-50..52
  async listEvents(pid, f = {}) {
    await wait(70)
    state(pid)
    return clone(
      (events[pid] ?? [])
        .filter((e) => (!f.item_id || e.item_id === f.item_id) && (!f.case_id || e.case_id === f.case_id))
        .reverse(),
    )
  },
  async appendEvent(pid, ev, reviewer) {
    await wait(90)
    if (!reviewer) throw new ProblemError(428, 'reviewer-required', 'Reviewer name required')
    state(pid)
    return appendEventSync(pid, ev, reviewer, SESSION_ID)
  },
  async phaseEvents(pid, f = {}) {
    await wait(50)
    state(pid)
    return clone((phaseEvents[pid] ?? []).filter((e) => (!f.case_id || e.case_id === f.case_id) && (!f.scan_idx || e.scan_idx === f.scan_idx)).reverse())
  },
  async appendPhase(pid, ev, reviewer) {
    await wait(70)
    if (!reviewer) throw new ProblemError(428, 'reviewer-required', 'Reviewer name required')
    const s = state(pid)
    const vocab = s.project.phase_vocabulary ?? []
    if (vocab.length && !vocab.includes(ev.value)) throw new ProblemError(422, 'validation', 'Phase not in the vocabulary', `allowed: ${vocab.join(', ')}`)
    const e: PhaseEvent = { event_id: ulid(), at: now(), reviewer, session_id: SESSION_ID, accepted_run_id: null, ...ev }
    ;(phaseEvents[pid] ??= []).push(e)
    // PHS-03: the selection wins over the index-time value, which stays in `resolved`
    for (const it of s.items)
      if (it.case_id === ev.case_id && it.scan_idx === ev.scan_idx) it.phase = { canonical: ev.value, raw: it.phase.raw ?? null, source: 'manual', resolved: it.phase.resolved ?? it.phase }
    emit(pid, { event: 'phase.appended', data: e })
    return clone(e)
  },
  async exportPhase() {
    await wait(60)
    return { dir: 'exports', files: ['phase_selections.json'], at: now() }
  },
  async curationState(pid) {
    await wait(70)
    state(pid)
    return [...latestState(pid).values()].map((e) => ({
      item_id: e.item_id, case_id: e.case_id, target: e.target, status: e.status, priority: e.priority,
      comment: e.comment, reviewer: e.reviewer, at: e.at, event_id: e.event_id, add_to_queue: e.add_to_queue,
      proposed_side: e.proposed_side, seg_id: segOf(e),
    }))
  },
  async queue(pid) {
    await wait(90)
    return queueRows(pid)
  },
  async queueCsv(pid) {
    await wait(60)
    const cols = ['case_id', 'item_id', 'scope', 'side', 'phase', 'target', 'seg_id', 'status', 'priority', 'comment', 'reviewer', 'at', 'image_path_abs', 'mask_path_abs'] as const
    const esc = (v: unknown) => (/[",\n]/.test(String(v ?? '')) ? `"${String(v).replaceAll('"', '""')}"` : String(v ?? ''))
    const lines = [cols.join(','), ...queueRows(pid).map((r) => cols.map((c) => esc(r[c])).join(','))]
    return new Blob([`${lines.join('\n')}\n`], { type: 'text/csv' })
  },
  async curationExports(pid) {
    await wait(200)
    state(pid)
    return { dir: 'exports', files: ['curation_state.csv', 'events.jsonl'], at: now() }
  },
  async importV2(pid) {
    await wait(200)
    state(pid)
    throw new ProblemError(503, 'server-busy', 'Not available in the mock', 'v2 import needs the backend (API-54)')
  },

  // API-30..37
  async radiomicsSchema() {
    await wait(120)
    return clone((await loadEngine()).schema)
  },
  async validateRadiomics(settings, labels, nItems) {
    await wait(40)
    return (await loadEngine()).validate(settings, labels, nItems)
  },
  async listProfiles(pid) {
    await wait(60)
    return clone(await profilesOf(state(pid)))
  },
  async saveProfile(pid, name, settings) {
    await wait(120)
    const s = state(pid)
    const list = await profilesOf(s)
    const e = await loadEngine()
    const norm = e.normalize(settings)
    const hash = profileHash(norm)
    const known = list.find((p) => p.profile_hash === hash)
    if (known) return clone(known)
    const p: Profile = { profile_hash: hash, name, created_at: now(), updated_at: now(), engine: engineOf(e.schema), settings: norm }
    list.push(p)
    return clone(p)
  },
  async renameProfile(pid, hash, name) {
    await wait(80)
    const p = (await profilesOf(state(pid))).find((x) => x.profile_hash === hash)
    if (!p) throw new ProblemError(404, 'not-found', 'Profile not found', hash)
    p.name = name
    p.updated_at = now()
    return clone(p)
  },
  async deleteProfile(pid, hash) {
    await wait(80)
    const s = state(pid)
    const list = await profilesOf(s)
    if (!list.some((x) => x.profile_hash === hash)) throw new ProblemError(404, 'not-found', 'Profile not found', hash)
    s.profiles = list.filter((x) => x.profile_hash !== hash)
    return clone(s.profiles)
  },
  async estimate(pid, _settings, selection) {
    await wait(500)
    const s = state(pid)
    const items = selectItems(s.items, selection, valueOf(s))
    const labels = selection.labels ?? []
    const n_units = items.length * labels.length
    const n_skipped = items.filter((i) => labels.some((l) => !i.labels_present.includes(l))).length
    return {
      n_items: items.length, n_labels: labels.length, n_units, n_skipped,
      sample_item_ids: items.slice(0, 3).map((i) => i.item_id),
      time_per_item_s: 2.4, time_per_unit_s: 1.2, workers: 2,
      estimated_total_s: Math.round((n_units * 1.2) / 2), sample_errors: [],
    }
  },
  async listRuns(pid) {
    await wait(80)
    return state(pid).runs.map(toSummary).reverse()
  },
  async getRun(pid, rid) {
    await wait(60)
    return clone(runOf(state(pid), rid))
  },
  async startRun(pid, body, reviewer) {
    await wait(200)
    const s = state(pid)
    const e = await loadEngine()
    const settings = e.normalize(body.settings)
    const items = selectItems(s.items, body.selection, valueOf(s))
    const labels = body.selection.labels ?? []
    const run: RunDetail = {
      run_id: ulid(), name: body.name, status: 'queued', created_at: now(), started_at: null, finished_at: null, reviewer,
      engine: { ...e.schema.engine, deps: {} }, ibsi_map_version: e.schema.ibsi_map_version, profile_hash: profileHash(settings), settings,
      selection: { scope: body.selection.scope ?? 'complete', labels, filter: body.selection.filter ? JSON.stringify(body.selection.filter) : null, item_ids: items.map((i) => i.item_id), seg_id: body.selection.seg_id ?? 'imported' },
      inputs: items.map((i) => ({ item_id: i.item_id, image_fp: null, seg_id: body.selection.seg_id ?? 'imported', mask_fp: null })),
      counts: { items: items.length, ok: 0, failed: 0, features: 0, skipped: 0 },
      job_id: null, error: null, progress: null,
    }
    s.runs.push(run)
    execute(pid, s, run)
    return clone(run)
  },
  async cancelRun(pid, rid) {
    await wait(60)
    const run = runOf(state(pid), rid)
    if (run.status !== 'queued' && run.status !== 'running') throw new ProblemError(409, 'conflict', 'Run is not active', rid)
    const j = run.job_id ? jobs.get(run.job_id) : undefined
    run.status = 'cancelled'
    run.finished_at = now()
    if (j && j.status === 'running') {
      j.status = 'cancelled'
      j.finished_at = now()
      emit(pid, { event: 'job.finished', data: { job_id: j.job_id, kind: j.kind, status: j.status, ref: j.ref } })
    }
    return clone(run)
  },
  async resumeRun(pid, rid) {
    await wait(60)
    const s = state(pid)
    const run = runOf(s, rid)
    if (run.status !== 'interrupted' && run.status !== 'cancelled') throw new ProblemError(409, 'conflict', 'Run cannot be resumed', rid)
    run.status = 'queued'
    run.finished_at = null
    execute(pid, s, run)
    return clone(run)
  },
  async runFeatures(pid, rid, itemId) {
    await wait(90)
    return featureRows(state(pid), rid, itemId)
  },
  runExportUrl(pid, rid, format, shape) {
    const s = db.get(pid)
    if (!s || format !== 'csv') return 'data:text/plain,Not%20available%20in%20the%20mock'
    return `data:text/csv;charset=utf-8,${encodeURIComponent(featuresCsv(featureRows(s, rid), shape))}`
  },
  async runErrors(pid, rid) {
    await wait(60)
    const s = state(pid)
    runOf(s, rid)
    return clone(s.errors[rid] ?? [])
  },

  // API-38/39 (mockDashboardView covers the QC views; the guided statistics need the backend)
  async dashboardView(pid, rid, view, body) {
    await wait(160)
    const s = state(pid)
    if (!s.runs.some((r) => r.run_id === rid)) throw new ProblemError(404, 'not-found', 'Run not found', rid)
    // worst decision per case (the server colours by item status)
    const statusOf = new Map<string, CurationStatus>()
    for (const e of latestState(pid).values()) statusOf.set(e.case_id, rollup([statusOf.get(e.case_id) ?? 'not_reviewed', e.status]))
    return mockDashboardView(view, body, { rows: featureRows(s, rid), errors: s.errors[rid] ?? [], run: s.runs.find((r) => r.run_id === rid), statusOf })
  },
  async listAnalyses(pid) {
    await wait(60)
    state(pid)
    return []
  },
  async getAnalysis(pid, aid) {
    await wait(60)
    state(pid)
    throw new ProblemError(404, 'not-found', 'Analysis not found', aid)
  },
  async createAnalysis() {
    await wait(120)
    throw new ProblemError(503, 'server-busy', 'Not available in the mock', 'Guided statistics need the backend (API-39)')
  },
  async exportAnalysis(_pid, aid) {
    await wait(60)
    throw new ProblemError(404, 'not-found', 'Analysis not found', aid)
  },

  // API-41
  async listJobs(pid) {
    await wait(40)
    return clone([...jobs.values()].filter((j) => !pid || j.project_id === pid)).reverse()
  },
  async cancelJob(pid, jobId) {
    await wait(60)
    const j = jobs.get(jobId)
    if (j && j.status === 'running') {
      j.status = 'cancelled'
      j.finished_at = now()
      const run = db.get(pid)?.runs.find((r) => r.run_id === j.ref)
      if (run) run.status = 'cancelled'
      emit(pid, { event: 'job.finished', data: { job_id: j.job_id, kind: j.kind, status: j.status, ref: j.ref } })
    }
  },
}
