// Domain payload types (DATA_MODEL, CURATION, RADIOMICS). Hand-written for the P0.5 mock;
// P2 replaces them with aliases of the generated `schema.d.ts` (FE-03).

export type Phase = 'NC' | 'CMP' | 'NP' | 'EP' | 'UNK'
export const PHASES: Phase[] = ['NC', 'CMP', 'NP', 'EP', 'UNK']
export type Scope = 'complete' | 'voi'
export type Side = 'L' | 'R' | '-' | string

export interface Project {
  project_id: string
  name: string
  created_at: string
  last_opened_at: string
  n_cases: number
  n_items: number
  progress: { reviewed: number; total: number }
  roots: { alias: string; path: string; reachable: boolean }[]
  label_map: LabelDef[]
  share_url: string
}

export interface LabelDef {
  value: number
  name: string
  color: string
  opacity: number
  visible: boolean
}

export interface ItemRecord {
  item_id: string
  case_id: string
  scan_idx: string
  scope: Scope
  side: Side
  patient_id: string
  group: string
  phase: { canonical: Phase; raw: string; source: string }
  image: { ref: string; format: string } | null
  mask: { ref: string; format: string } | null
  geometry: { shape: number[]; spacing: number[]; dtype: string; orientation: string } | null
  labels_present: number[]
  status: 'active' | 'excluded_upstream' | 'missing'
  warning_codes: string[]
  extra: Record<string, unknown>
}

export interface CaseSummary {
  case_id: string
  patient_id: string
  group: string
  phases: Phase[]
  n_scans: number
  n_items: number
  has_seg: boolean
  has_voi_L: boolean
  has_voi_R: boolean
  n_warnings: number
  curation_status: CurationStatus
  last_reviewed_at: string | null
  thumb_item_id: string | null
  excluded: boolean
}

export interface CaseDetail {
  summary: CaseSummary
  items: ItemRecord[]
  warnings: QCWarning[]
}

export interface QCWarning {
  code: string
  severity: 'error' | 'warning'
  item_id: string | null
  case_id: string
  message: string
  detected_at: string
}

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

export type JobKind = 'indexing' | 'thumbnails' | 'radiomics' | 'mesh' | 'hash'
export interface Job {
  job_id: string
  kind: JobKind
  title: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  done: number
  total: number
  eta_s: number | null
  started_at: string
  ref: string | null
}

export interface FsEntry {
  name: string
  path: string
  kind: 'dir' | 'file'
  detected?: string[]
}

export interface ImportPreview {
  root: string
  detected: { file: string; found: boolean; rows: number }[]
  n_rows: number
  n_cases: number
  n_items: number
  errors: { row: number; code: string; message: string }[]
  mapping: { field: string; source: string }[]
}

export interface Problem {
  type: string
  title: string
  status: number
  detail?: string
}

export type ServerEvent =
  | { event: 'curation.appended'; data: CurationEvent }
  | { event: 'job.progress'; data: Job }
  | { event: 'job.finished'; data: Job }
  | { event: 'index.rebuilt'; data: { import_id: string; n_items: number; n_warnings: number } }
  | { event: 'project.updated'; data: { fields: string[] } }
