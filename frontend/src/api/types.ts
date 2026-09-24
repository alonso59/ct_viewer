// Domain payload types. Built endpoints alias the generated `schema.d.ts` (FE-03); the HTTP client
// normalizes payloads into these shapes so features stay independent of wire details.
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
/** API-06 import report (PRJ-09): the new project and a per-alias resolve check */
export type BundleImportResult = S['BundleImportResult']
/** API-06 export: the `.zip` and its server-chosen file name (PRJ-08) */
export interface ProjectBundle {
  blob: Blob
  filename: string
}
/** API-15 `202` (IMP-09): progress arrives as `job.*` events of kind `hash` */
export type HashJobStarted = S['HashJobStarted']

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

/** CUR §Event schema: audit snapshot; the server adds fingerprints, phase and import id */
export interface CurationContext {
  viewer?: { axis: string; slice: number; ww: number; wl: number }
  image_fp?: string
  mask_fp?: string
  phase?: string
  import_id?: string
}

/** API-50 event (CUR §Event schema) */
export type CurationEvent = Omit<Required<S['CurationEvent']>, 'context'> & { context: CurationContext }

export type NewCurationEvent = Pick<
  CurationEvent,
  'item_id' | 'case_id' | 'target' | 'status' | 'priority' | 'comment' | 'add_to_queue'
> &
  Partial<Pick<CurationEvent, 'proposed_phase' | 'proposed_side' | 'context' | 'seg_id'>>

/** CUR-08 derived state, one row per `(item_id, target)`; `item_id = null` for case targets.
 *  Flattened from API-51 `CurationState` (items[].targets, cases[].targets). */
export interface CurationStateRow {
  item_id: string | null
  case_id: string
  target: string
  status: CurationStatus
  priority: Priority
  comment: string
  reviewer: string
  at: string
  event_id: string
  add_to_queue: boolean
  proposed_phase: string | null
  proposed_side: 'L' | 'R' | null
}

/** API-52 row (CUR §Correction queue CSV columns); absolute paths resolved by the server */
export type QueueRow = Required<S['QueueRow']>
/** API-53 result: files written into the project's `exports/` */
export type CurationExport = S['ExportResult']
/** API-54 report */
export type V2ImportReport = S['V2ImportReport']

// ---- radiomics (API-30..37), from the generated schema ----------------------------------------
/** API-30 engine schema (RAD-01) */
export type SettingsSchema = S['SettingsSchema']
export type OptionSpec = S['OptionSpec']
export type FilterSpec = S['FilterSpec']
export type FeatureClassSpec = S['FeatureClassSpec']
/** Engine settings snapshot sent to API-31/33/34 and stored in profiles */
export type RadiomicsSettings = S['RadiomicsSettings']
/** API-31 finding; `loc` is the path into `RadiomicsSettings` (or `labels`, `n_items`) */
export type ValidationIssue = S['Issue']
export type ValidateResult = S['ValidateResult']
/** API-33/34 item selection (RAD-05) */
export type Selection = S['Selection']
export type SelectionFilter = S['SelectionFilter']
/** API-33 pre-run estimate (RAD-11) */
export type EstimateResult = S['EstimateResult']
/** API-32 profile; identified by `profile_hash` (RAD-03) */
export type Profile = S['app__radiomics__models__Profile']
/** API-34 list row and detail */
export type RunSummary = S['RunSummary']
export type RunDetail = S['RunDetail']
export type RunStatus = RunSummary['status']
/** API-37 per-item failure (RAD-07) */
export type RunError = S['app__radiomics__models__RunError']
/** API-34 start body */
export interface StartRunBody {
  name: string
  settings: RadiomicsSettings
  selection: Selection
}
export type RunExportFormat = 'csv' | 'parquet'
export type RunExportShape = 'long' | 'wide'

/** API-36 long rows (RAD §Output schema). `feature` is the full column name used by API-38/39
 *  (`{image_type}_{feature_class}_{name}`, e.g. `original_firstorder_Mean`). */
export interface FeatureRow {
  item_id: string
  case_id: string
  scan_idx: string
  scope: Scope
  side: Side
  phase: string
  label: number
  image_type: string
  feature_class: string
  feature: string
  /** null = NaN/inf in the output */
  value: number | null
  ibsi_code: string | null
  ibsi_status: 'compliant' | 'deviates' | 'not_defined' | null
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
  /** SRC-03/04: `nifti-files` builds v1 rows from file names; `root` may be one NIfTI file (SRC-05) */
  adapter?: ImportAdapter
  options?: NiftiOptions
  /** SRC-15: keep the project's other sources (SOURCES §Imports) */
  add?: boolean
}
export type ImportAdapter = NonNullable<S['ImportPreview']['adapter']>
/** `nifti-files` options (SOURCES §NIfTI files) */
export interface NiftiOptions {
  pattern?: string
  case_id_from?: 'pattern' | 'stem' | 'sequential'
  modality?: string
  include?: string[] | null
  mask_conventions?: string[]
}
export type ParsedFile = S['ParsedFile']
/** API-19 */
export type DetectResult = S['DetectResult']
export type DetectCandidate = S['Candidate']
/** API-07/08 Open mode (SRC-09/10) */
export type OpenSession = S['OpenSession']
export type OpenItem = S['OpenItem']
export type AxisOrder = 'xyz' | 'zyx'

// ---- Study variables (VARIABLES.md, API-16..18) -----------------------------------------------
// Enums come from the generated schema (FE-03). The UI works on `Variable`, adapted from the
// API-16/17 `Catalog` in http.ts (profile `distinct`/`top` → `n_distinct`/`levels`, derived
// definitions joined in, bin `quantiles` as a group count instead of cut probabilities).
type WireVariable = S['Variable']
export const VARIABLE_TYPES = ['continuous', 'categorical', 'numeric-discrete', 'date', 'identifier', 'text', 'constant'] as const satisfies readonly WireVariable['type'][]
export type VariableType = WireVariable['type']
/** Types a user can pick when confirming or overriding an inference (VAR-03; API `VariableOverride.type`) */
export const OVERRIDE_TYPES = ['continuous', 'categorical', 'date', 'identifier', 'text'] as const satisfies readonly NonNullable<S['VariableOverride']['type']>[]
export type OverrideType = (typeof OVERRIDE_TYPES)[number]
export const VARIABLE_TAGS = ['confounder', 'outcome', 'sensitive'] as const satisfies readonly NonNullable<WireVariable['tags']>[number][]
export type VariableTag = (typeof VARIABLE_TAGS)[number]
export type VariableSource = WireVariable['source']
export type VariableGroup = WireVariable['group']

export interface VariableProfile {
  missing_pct: number
  n_distinct: number
  examples: string[]
  /** Numeric values only */
  min?: number | null
  max?: number | null
  /** Level-like types only (categorical, numeric-discrete, constant): most frequent levels → count */
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
  level: WireVariable['level']
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

/** API-16 PATCH body (`VariableOverride`) */
export interface VariablePatch {
  type?: OverrideType
  visible?: boolean
  tags?: VariableTag[]
}

/** API-18 match report (`ExternalReport`), in UI terms */
export interface ExternalImportResult {
  key: 'case_id' | 'patient_id'
  n_rows: number
  matched: number
  unmatched_keys: string[]
  /** Keys that occur more than once in the table (the first row wins) */
  duplicate_keys: string[]
  /** Columns skipped because the name is already taken */
  conflicts: string[]
  /** Columns added as variables */
  added: string[]
}

// ---- Dashboard views (API-38) and guided analysis (API-39): generated types (FE-03) ----------
export type GlobalFilters = S['GlobalFilters']
export type ColorBy = S['ColorBy']
export type UnitSpec = S['UnitSpec']
export type UnitSummary = S['UnitSummary']
export type TestChoice = S['TestChoice']
export type ResultRow = S['ResultRow']
export type DescriptiveRow = S['DescriptiveRow']
export type Recommendation = S['Recommendation']
export type AnalysisSpec = S['AnalysisSpec']
export type Analysis = S['Analysis']
export type AnalysisSummary = S['AnalysisSummary']
export type AnalysisQuestion = AnalysisSpec['question']
export type AnalysisExportFile = 'tidy' | 'results' | 'descriptives' | 'spec'

/** Request body: fields with a server default are optional (openapi-typescript marks them required) */
type Body<T, K extends keyof T = never> = Partial<T> & Pick<T, K>

/** API-38 `{view}` → request body / response (DASHBOARD §Views) */
export interface DashboardViews {
  'run-overview': { req: Body<S['RunOverviewRequest']>; res: S['RunOverviewResponse'] }
  'feature-distribution': { req: Body<S['FeatureDistributionRequest'], 'feature'>; res: S['FeatureDistributionResponse'] }
  'missing-matrix': { req: Body<S['MissingMatrixRequest']>; res: S['MissingMatrixResponse'] }
  correlation: { req: Body<S['CorrelationRequest']>; res: S['CorrelationResponse'] }
  embedding: { req: Body<S['EmbeddingRequest']>; res: S['EmbeddingResponse'] }
  outliers: { req: Body<S['OutliersRequest']>; res: S['OutliersResponse'] }
  'feature-vs-volume': { req: Body<S['FeatureVsVolumeRequest'], 'feature'>; res: S['FeatureVsVolumeResponse'] }
  'group-comparison': { req: Body<S['GroupComparisonRequest'], 'variable'>; res: S['GroupComparisonResponse'] }
  association: { req: Body<S['AssociationRequest'], 'variable'>; res: S['AssociationResponse'] }
  balance: { req: Body<S['BalanceRequest'], 'variable' | 'other'>; res: S['BalanceResponse'] }
  'phase-side-consistency': { req: Body<S['ConsistencyRequest'], 'feature'>; res: S['ConsistencyResponse'] }
}
export type DashboardView = keyof DashboardViews
export const DASHBOARD_VIEWS = [
  'run-overview',
  'feature-distribution',
  'missing-matrix',
  'correlation',
  'embedding',
  'outliers',
  'feature-vs-volume',
  'group-comparison',
  'association',
  'balance',
  'phase-side-consistency',
] as const satisfies readonly DashboardView[]
export type ViewRequest<V extends DashboardView> = DashboardViews[V]['req']
export type ViewResponse<V extends DashboardView> = DashboardViews[V]['res']

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
  | { event: 'job.status'; data: Pick<Job, 'job_id' | 'status'> }
  | { event: 'index.rebuilt'; data: { import_id: string; n_items: number; n_warnings: number } }
  | { event: 'project.updated'; data: { fields: string[] } }

// ---- P7b: tasks (API-42..47, TSK-*) and segmentation sets (API-27, ADR-0015) --------------------
export type RootRole = S['PathRoot']['role']
export type SegmentationSet = S['SegmentationSet']
export type SegmentationInfo = S['SegmentationInfo']
export type SegmentationPatch = S['SegmentationPatch']
export type TaskManifest = S['TaskManifest']
export type TaskInfo = S['TaskInfo']
export type TaskList = S['TaskList']
export type TaskSelection = S['TaskSelection']
export type TaskValidateResult = S['TaskValidateResult']
export type PreflightResult = S['PreflightResult']
export type TaskEstimate = S['TaskEstimate']
export type TaskRunRequest = S['TaskRunRequest']
export type TaskRunStarted = S['TaskRunStarted']
export type TaskRunSummary = S['TaskRunSummary']
export type TaskRunDetail = S['TaskRunDetail']
export type TaskRunStatus = TaskRunSummary['status']
export type TaskItemError = S['TaskItemError']
export type TaskRunOutput = S['TaskRunOutput']
export type AnnotationRow = S['AnnotationRow']
export type AnnotationSources = S['AnnotationSources']
/** API-09 (SRC-14) */
export type SaveOpenBody = S['SaveBody']
export type SavedOpen = S['Saved']

// ---- P7c: plugins (API-49, PLG-*) ------------------------------------------------------------------
export type PluginManifest = S['PluginManifest']
export type PluginInfo = S['PluginInfo']
export type PluginList = S['PluginList']
export type PluginStatus = PluginInfo['status']
