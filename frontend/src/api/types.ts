// Domain payload types. Built endpoints alias the generated `schema.d.ts` (FE-03); the HTTP client
// normalizes payloads into these shapes so features stay independent of wire details.
// Endpoints not built yet (curation API-50..54, radiomics API-30..38, variables API-16..18) keep
// hand-written types from the domain docs until their backend lands and `make gen-api` covers them.
import type { components } from './schema'

type S = components['schemas']

export type Phase = S['PhaseInfo']['canonical']
export const PHASES: Phase[] = ['NC', 'CMP', 'NP', 'EP', 'UNK']
export type Scope = S['Item']['scope']
export type Side = S['Item']['side']
export type QcCode = S['QcCode']

/** PRJ-12 study presets */
export const PRESETS = ['ccrcc', 'generic-ct', 'none'] as const
export type Preset = (typeof PRESETS)[number]

/** API-02 list row */
export type ProjectSummary = Omit<S['ProjectSummary'], 'last_opened_at'> & { last_opened_at: string | null }

export type LabelDef = Required<S['LabelEntry']>
export type PathRoot = S['PathRoot']
export type RootInfo = S['RootInfo']
export type RelinkResult = S['RelinkResult']

/** API-03 detail */
export type Project = Omit<Required<S['ProjectDetail']>, 'label_map'> & { label_map: LabelDef[]; preset?: Preset | null }

export type VolumeRef = S['VolumeRef']
export type Geometry = S['Geometry']

/** API-22 item; server defaults make every field present */
export type ItemRecord = Required<S['Item']>
export type ItemDetail = ItemRecord & {
  /** `image_abs`/`mask_abs` alias the API names for P0.5 code (viewer ImageSection); drop after lane/2-viewer merges */
  advanced: Required<S['ItemAdvanced']> & { image_abs: string | null; mask_abs: string | null }
  warnings: QCWarning[]
}

export type VariableValue = string | number | null

export type CaseSummary = Omit<Required<S['CaseSummary']>, 'group' | 'curation_status'> & {
  curation_status: CurationStatus
  /** Case-level values of study variables (VAR-02/10); `{}` until the backend sends them */
  variables: Record<string, VariableValue>
  /** Item used for the list thumbnail; null = derive it from the case detail */
  thumb_item_id: string | null
  excluded: boolean
}

export interface CaseDetail {
  summary: CaseSummary
  items: ItemRecord[]
  warnings: QCWarning[]
}

export type QCWarning = Required<S['QcWarning']>
export type Severity = S['Severity']

export const CURATION_STATUSES = [
  'not_reviewed',
  'accepted',
  'needs_minor_correction',
  'needs_major_correction',
  'rejected',
  'wrong_phase_suspected',
  'wrong_side_suspected',
  'missing',
  'cannot_assess',
] as const
export type CurationStatus = (typeof CURATION_STATUSES)[number]

// CUR §Status: rollup severity and queue membership
export const STATUS_SEVERITY: Record<CurationStatus, number> = {
  rejected: 8,
  needs_major_correction: 7,
  wrong_phase_suspected: 6,
  wrong_side_suspected: 6,
  needs_minor_correction: 5,
  missing: 4,
  cannot_assess: 3,
  accepted: 1,
  not_reviewed: 0,
}
export const QUEUE_STATUSES: CurationStatus[] = [
  'rejected',
  'needs_major_correction',
  'wrong_phase_suspected',
  'wrong_side_suspected',
  'needs_minor_correction',
  'missing',
]

export type Priority = 'low' | 'medium' | 'high'

export interface CurationEvent {
  event_id: string
  schema_version: 1
  at: string
  reviewer: string
  session_id: string
  item_id: string | null
  case_id: string
  target: string
  status: CurationStatus
  priority: Priority
  comment: string
  proposed_phase: Phase | null
  proposed_side: 'L' | 'R' | null
  add_to_queue: boolean
  context: { viewer?: { axis: string; slice: number; ww: number; wl: number }; phase?: Phase }
  source: 'ui' | 'v2_import' | 'api'
}

export type NewCurationEvent = Pick<
  CurationEvent,
  'item_id' | 'case_id' | 'target' | 'status' | 'priority' | 'comment' | 'add_to_queue'
> &
  Partial<Pick<CurationEvent, 'proposed_phase' | 'proposed_side' | 'context'>>

export interface CurationStateRow {
  item_id: string | null
  case_id: string
  target: string
  status: CurationStatus
  priority: Priority
  comment: string
  reviewer: string
  at: string
  add_to_queue: boolean
}

export type QueueRow = CurationStateRow & { item: ItemRecord | null; image_abs: string | null; mask_abs: string | null }

export type RunStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'completed_with_errors'
  | 'failed'
  | 'cancelled'
  | 'interrupted'

export interface RadiomicsRun {
  run_id: string
  name: string
  status: RunStatus
  created_at: string
  started_at: string | null
  finished_at: string | null
  reviewer: string
  engine: { name: string; version: string }
  profile_hash: string
  selection: { scope: Scope; labels: number[]; filter: string }
  counts: { items: number; ok: number; failed: number; features: number }
}

export interface FeatureValue {
  item_id: string
  label: number
  feature_class: string
  feature: string
  value: number
}

/** API-36 JSON rows carry the item columns of the output schema (RAD §Output schema) */
export interface FeatureRow extends FeatureValue {
  case_id: string
  scan_idx: string
  scope: Scope
  side: Side
  phase: Phase
  /** Dashboard colouring; moves to study variables in P6-FE (VAR-10) */
  group: string
}

export interface RunError {
  item_id: string
  label: number
  error: string
}

// API-30 settings schema (RAD-01): every option with type, default, constraints and group
export type OptionType = 'bool' | 'int' | 'float' | 'text' | 'select' | 'float_list' | 'int_list'
export interface SettingsOption {
  key: string
  title: string
  type: OptionType
  default: unknown
  help?: string
  min?: number
  max?: number
  choices?: string[]
  nullable?: boolean
  /** Only shown/enabled when this boolean option is on (e.g. LoG → sigma) */
  parent?: string
}
export interface SettingsGroup {
  id: string
  title: string
  options: SettingsOption[]
  /** Feature classes: per-feature checkboxes (RAD-02) */
  features?: Record<string, string[]>
}
export interface SettingsSchema {
  engine: { name: string; version: string }
  groups: SettingsGroup[]
}
export type Settings = Record<string, unknown>
export interface Issue {
  field: string | null
  severity: 'error' | 'warning'
  message: string
}
export interface Profile {
  name: string
  hash: string
  settings: Settings
  saved_at: string
}
export interface Estimate {
  n_items: number
  n_labels: number
  n_extractions: number
  sec_per_item: number
}

/** API-41 job */
export type Job = Required<S['JobInfo']>
export type JobKind = Job['kind']
export type JobStatus = Job['status']
/** API-40 `job.progress` / `job.finished` payloads */
export type JobProgress = Pick<Job, 'job_id' | 'kind' | 'done' | 'total' | 'eta_s'>
export type JobFinished = Pick<Job, 'job_id' | 'kind' | 'status' | 'ref'>

export type FsEntry = Required<S['FsEntry']>
export type FsListing = Omit<S['FsListing'], 'entries' | 'truncated'> & { entries: FsEntry[]; truncated: boolean }
export type ImportPreview = S['ImportPreview']
export type ImportHistory = S['ImportHistory']
export type IndexStatus = S['IndexStatus']
export type CommitResult = S['CommitResult']
export type Health = S['Health']

/** Import preview request: a server folder (IMP-01/02), optionally with uploaded metadata files */
export interface PreviewRequest {
  root: string
  alias: string
  files?: { metadata: File; phase?: File | null; voi_catalog?: File | null }
}

// ---- Study variables (VARIABLES.md, API-16..18): proposed wire shape until lane/2-backend lands ----
export const VARIABLE_TYPES = ['continuous', 'categorical', 'numeric-discrete', 'date', 'identifier', 'text', 'constant'] as const
export type VariableType = (typeof VARIABLE_TYPES)[number]
/** Types a user can pick when confirming or overriding an inference (VAR-03) */
export const OVERRIDE_TYPES: VariableType[] = ['continuous', 'categorical', 'date', 'identifier', 'text']
export const VARIABLE_TAGS = ['confounder', 'outcome', 'sensitive'] as const
export type VariableTag = (typeof VARIABLE_TAGS)[number]
export type VariableSource = 'metadata' | 'derived' | 'external' | 'raw'
export type VariableGroup = 'study' | 'acquisition'

export interface VariableProfile {
  missing_pct: number
  n_distinct: number
  examples: (string | number)[]
  /** Continuous only */
  min?: number | null
  max?: number | null
  /** Categorical only: level → count */
  levels?: { value: string; count: number }[]
}

export type DerivedDef =
  | { name: string; op: 'bin'; source: string; thresholds?: number[]; quantiles?: number; labels: string[] }
  | { name: string; op: 'recode'; source: string; map: Record<string, string> }
  | { name: string; op: 'dominant'; sources: string[] }
export type DerivedOp = DerivedDef['op']

export interface Variable {
  name: string
  source: VariableSource
  type: VariableType
  /** The inference before any override */
  inferred_type: VariableType
  level: 'case' | 'scan'
  group: VariableGroup
  tags: VariableTag[]
  visible: boolean
  /** 0..1 */
  confidence: number
  /** Low-confidence inference: the UI shows a "Review" badge until confirmed (VAR-03) */
  review: boolean
  overridden: boolean
  profile: VariableProfile
  definition?: DerivedDef | null
}

export type VariablePatch = Partial<Pick<Variable, 'type' | 'visible' | 'tags'>>

export interface ExternalImportResult {
  key: 'case_id' | 'patient_id'
  n_rows: number
  matched: number
  unmatched_keys: string[]
  added: string[]
}

export interface Problem {
  type: string
  title: string
  status: number
  detail?: string
}

export type ServerEvent =
  | { event: 'curation.appended'; data: CurationEvent }
  | { event: 'job.progress'; data: JobProgress }
  | { event: 'job.finished'; data: JobFinished }
  | { event: 'index.rebuilt'; data: { import_id: string; n_items: number; n_warnings: number } }
  | { event: 'project.updated'; data: { fields: string[] } }
