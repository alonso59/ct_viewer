// Domain payload types. Built endpoints alias the generated `schema.d.ts`; the HTTP client
// normalizes payloads into these shapes so features stay independent of wire details.
import type { components } from './schema'

type S = components['schemas']

export type Phase = S['PhaseInfo']['canonical']
export const PHASES: Phase[] = ['NC', 'CMP', 'NP', 'EP', 'UNK']
export type Scope = S['Item']['scope']
export type Side = S['Item']['side']

/** Default modality of a neutral project */
export const MODALITIES = ['CT', 'MR', 'mixed'] as const
export type ProjectModality = (typeof MODALITIES)[number]

export type ProjectSummary = Omit<S['ProjectSummary'], 'last_opened_at'> & { last_opened_at: string | null }

export type LabelDef = Required<S['LabelEntry']>
export type RootInfo = S['RootInfo']
export type RelinkResult = S['RelinkResult']
/** Bundle import report: the new project and a per-alias resolve check */
export type BundleImportResult = S['BundleImportResult']
/** Bundle export: the `.zip` and its server-chosen file name */
export interface ProjectBundle {
  blob: Blob
  filename: string
}
/** `202`: progress arrives as `job.*` events of kind `hash` */
export type HashJobStarted = S['HashJobStarted']

export type Project = Omit<Required<S['ProjectDetail']>, 'label_map'> & { label_map: LabelDef[] }
/** Sent with `If-Match` */
export type ProjectPatch = S['ProjectPatch']
export type DisplaySettings = S['Display']
export type PackInfo = S['PackInfo']
export type PackApplied = S['PackApplied']
/** View-only link */
export type ViewToken = S['ViewToken']


/** Server defaults make every field present */
export type ItemRecord = Required<S['Item']>
export type ItemPage = S['Page_Item_']
export interface ItemFilter {
  q?: string
  scope?: Scope
  phase?: string
  modality?: string
  has_mask?: boolean
  cursor?: string
  limit?: number
}
export type ItemDetail = ItemRecord & {
  advanced: Required<S['ItemAdvanced']>
  warnings: QCWarning[]
}

export type VariableValue = string | number | null

export type CaseSummary = Omit<Required<S['CaseSummary']>, 'group' | 'curation_status'> & {
  /** The worst decision, or `partially_reviewed` (see `review_state`) */
  curation_status: CaseRollup
  /** Case-level values of study variables; `{}` until the backend sends them */
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

export const CURATION_STATUSES = [
  'not_reviewed',
  'accepted',
  'needs_minor_correction',
  'needs_major_correction',
  'rejected',
  'wrong_side_suspected',
  'missing',
  'cannot_assess',
] as const
export type CurationStatus = (typeof CURATION_STATUSES)[number]
/** Case rollup values: a status, or `partially_reviewed` while an active item has no decision */
export const CASE_ROLLUPS = [...CURATION_STATUSES.slice(0, 1), 'partially_reviewed', ...CURATION_STATUSES.slice(1)] as const
export type CaseRollup = (typeof CASE_ROLLUPS)[number]

/** Statuses that put an item in the correction queue */
export const QUEUE_STATUSES: CurationStatus[] = [
  'rejected',
  'needs_major_correction',
  'wrong_side_suspected',
  'needs_minor_correction',
  'missing',
]

export type Priority = 'low' | 'medium' | 'high'

/** Audit snapshot; the server adds fingerprints, phase and import id */
export interface CurationContext {
  viewer?: { axis: string; slice: number; ww: number; wl: number }
  image_fp?: string
  mask_fp?: string
  phase?: string
  import_id?: string
}

export type CurationEvent = Omit<Required<S['CurationEvent']>, 'context'> & { context: CurationContext }

export type NewCurationEvent = Pick<
  CurationEvent,
  'item_id' | 'case_id' | 'target' | 'status' | 'priority' | 'comment' | 'add_to_queue'
> &
  Partial<Pick<CurationEvent, 'proposed_side' | 'context' | 'seg_id'>>

/** Derived curation state, one row per `(item_id, target, seg_id)`; `item_id = null` for case targets.
 *  Flattened from `CurationState` (items[].targets, cases[].targets). */
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
  proposed_side: 'L' | 'R' | null
  /** Mask targets: the segmentation set (`imported` when an old event had none); else null */
  seg_id: string | null
}

/** Absolute paths resolved by the server */
export type QueueRow = Required<S['QueueRow']>
/** Files written into the project's `exports/` */
export type CurationExport = S['ExportResult']
export type V2ImportReport = S['V2ImportReport']

export type SettingsSchema = S['SettingsSchema']
export type OptionSpec = S['OptionSpec']
export type FilterSpec = S['FilterSpec']
export type FeatureClassSpec = S['FeatureClassSpec']
/** Engine settings snapshot sent to validate, estimate and run, and stored in profiles */
export type RadiomicsSettings = S['RadiomicsSettings']
/** `loc` is the path into `RadiomicsSettings` (or `labels`, `n_items`) */
export type ValidationIssue = S['Issue']
export type ValidateResult = S['ValidateResult']
export type Selection = S['TaskSelection']
export type SelectionFilter = S['TaskSelectionFilter']
/** Pre-run estimate, `TaskEstimate.radiomics` */
export type EstimateResult = S['EstimateResult']
/** Identified by `profile_hash` */
export type Profile = S['app__radiomics__models__Profile']
/** List row and detail (`radiomics` of the task run) */
export type RunSummary = S['RunSummary']
export type RunDetail = S['RunDetail']
export type RunStatus = RunSummary['status']
/** Per-item failure, `TaskItemError.radiomics` */
export type RunError = S['app__radiomics__models__RunError']
/** Start body (task `radiomics.pyradiomics`) */
export interface StartRunBody {
  name: string
  settings: RadiomicsSettings
  selection: Selection
}
export type RunExportFormat = 'csv' | 'parquet'
export type RunExportShape = 'long' | 'wide'

/** Long feature rows. `feature` is the full column name used by the dashboard and analyses
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

export type Job = Required<S['JobInfo']>
export type JobStatus = Job['status']
/** `job.progress` / `job.finished` payloads */
export type JobProgress = Pick<Job, 'job_id' | 'kind' | 'done' | 'total' | 'eta_s'>
export type JobFinished = Pick<Job, 'job_id' | 'kind' | 'status' | 'ref'>

export type FsEntry = Required<S['FsEntry']>
export type FsListing = Omit<S['FsListing'], 'entries' | 'truncated'> & { entries: FsEntry[]; truncated: boolean }
export type ImportPreview = S['ImportPreview']
export type ImportHistory = S['ImportHistory']
export type CommitResult = S['CommitResult']
export type Health = S['Health']

/** Import preview request: a server folder, optionally with uploaded metadata files */
export interface PreviewRequest {
  root: string
  alias: string
  files?: { metadata: File; phase?: File | null; voi_catalog?: File | null }
  /** `nifti-files` builds v1 rows from file names; `root` may be one NIfTI file */
  adapter?: ImportAdapter
  /** `nifti-files` options, or `{reconstruct_sidecars}` for `metadata-v1` */
  options?: NiftiOptions | { reconstruct_sidecars: boolean }
  /** Keep the project's other sources */
  add?: boolean
}
export type ImportAdapter = NonNullable<S['ImportPreview']['adapter']>
export interface NiftiOptions {
  pattern?: string
  case_id_from?: 'pattern' | 'stem' | 'sequential'
  modality?: string
  include?: string[] | null
  mask_conventions?: string[]
  /** image → mask: the segmentation attached in Open mode */
  masks?: Record<string, string> | null
  /** The mask path from the pattern's groups, `{stem}`, `{dir}`; a folder is a mask set */
  mask_template?: string | null
}
export type DetectResult = S['DetectResult']
export type DetectCandidate = S['Candidate']
export type OpenSession = S['OpenSession']
export type OpenItem = S['OpenItem']
export type OpenItemPage = S['Page_OpenItem_']
export type AxisOrder = 'xyz' | 'zyx'

// The UI works on `Variable`, adapted from the wire `Catalog` in http.ts (profile
// `distinct`/`top` → `n_distinct`/`levels`, derived definitions joined in, bin `quantiles` as a
// group count instead of cut probabilities).
type WireVariable = S['Variable']
/** Derived definition that no longer builds, with the reason */
export type BrokenDerived = S['BrokenDerived']
export type VariableType = WireVariable['type']
/** Types a user can pick when confirming or overriding an inference (`VariableOverride.type`) */
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
  /** Low-confidence inference: the UI shows a "Review" badge until confirmed */
  review: boolean
  overridden: boolean
  /** Offered for side-by-side comparison (Labeling reference columns) */
  comparable: boolean
  profile: VariableProfile
  definition?: DerivedDef | null
}

/** PATCH body (`VariableOverride`) */
export interface VariablePatch {
  type?: OverrideType
  visible?: boolean
  tags?: VariableTag[]
}

/** Match report (`ExternalReport`), in UI terms */
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

export type GlobalFilters = S['GlobalFilters']
export type ColorBy = S['ColorBy']
export type UnitSpec = S['UnitSpec']
export type TestChoice = S['TestChoice']
export type ResultRow = S['ResultRow']
export type Recommendation = S['Recommendation']
export type AnalysisSpec = S['AnalysisSpec']
export type Analysis = S['Analysis']
export type AnalysisSummary = S['AnalysisSummary']
export type AnalysisQuestion = AnalysisSpec['question']
export type AnalysisExportFile = 'tidy' | 'results' | 'descriptives' | 'spec'

/** Request body: fields with a server default are optional (openapi-typescript marks them required) */
type Body<T, K extends keyof T = never> = Partial<T> & Pick<T, K>

/** Dashboard `{view}` → request body / response */
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
export type ViewRequest<V extends DashboardView> = DashboardViews[V]['req']
export type ViewResponse<V extends DashboardView> = DashboardViews[V]['res']

export interface Problem {
  type: string
  title: string
  status: number
  detail?: string
}

export type PhaseEvent = S['PhaseEvent']
/** POST body; the client adds the session id */
export type NewPhaseEvent = Omit<S['PhaseIn'], 'session_id'>
export type PhaseExport = S['PhaseExportResult']

export type ServerEvent =
  | { event: 'curation.appended'; data: CurationEvent }
  | { event: 'phase.appended'; data: PhaseEvent }
  | { event: 'labeling.appended'; data: LabelCellEvent }
  | { event: 'job.progress'; data: JobProgress }
  | { event: 'job.finished'; data: JobFinished }
  | { event: 'job.status'; data: Pick<Job, 'job_id' | 'status'> }
  | { event: 'index.rebuilt'; data: { import_id: string; n_items: number; n_warnings: number } }
  | { event: 'project.updated'; data: { fields: string[] } }
  /** Missed events cannot be replayed (server) or the stream reopened after an error
   *  (client): refetch everything of the project */
  | { event: 'reset'; data: Record<string, never> }

export type RootRole = S['PathRoot']['role']
export type SegmentationSet = S['SegmentationSet']
export type SegmentationInfo = S['SegmentationInfo']
export type SegmentationPatch = S['SegmentationPatch']
export type TaskInfo = S['TaskInfo']
export type TaskList = S['TaskList']
export type TaskSelection = S['TaskSelection']
export type TaskValidateResult = S['TaskValidateResult']
export type PreflightResult = S['PreflightResult']
export type TaskEstimate = S['TaskEstimate']
export type ConversionTimeEstimate = S['ConversionTimeEstimate']
export type EstimateProgress = S['EstimateProgress']
export type TaskRunRequest = S['TaskRunRequest']
export type TaskRunStarted = S['TaskRunStarted']
export type RunAttemptControl = S['RunAttemptControl']
/** A radiomics row carries its run summary (`radiomics`) */
export type TaskRunSummary = S['TaskRunListItem']
export type TaskRunDetail = S['TaskRunDetail']
export type TaskRunStatus = TaskRunSummary['status']
export type TaskItemError = S['TaskItemError']
export type TaskRunOutput = S['TaskRunOutput']
export type AnnotationRow = S['AnnotationRow']
export type AnnotationSources = S['AnnotationSources']
export type SaveOpenBody = S['SaveBody']
export type SavedOpen = S['Saved']

export type PluginInfo = S['PluginInfo']
export type PluginList = S['PluginList']
export type WorkspaceRun = S['WorkspaceRun']
export type WorkspaceRunRequest = S['WorkspaceRunRequest']
export type SourceOperation = S['SourceOperation']
export type SourceOperationStart = S['SourceOperationStart']
export type SourceOperationControl = S['SourceOperationControl']
export type SourceOperationEstimate = S['SourceOperationEstimate']
export type SourceOperationConvert = S['SourceOperationConvert']
export type SourcePlanPage = S['SourcePlanPage']
export type InventoryPage = S['InventoryPage']
export type LayerInfo = S['LayerInfo']

export type LabelTable = S['LabelTable']
export type LabelTableInfo = S['TableInfo']
export type LabelColumn = S['LabelColumn']
export type LabelColumnIn = S['ColumnIn']
export type LabelTableCreate = S['TableCreate']
export type LabelTablePatch = S['TablePatch']
export type LabelCellsPage = S['CellsPage']
export type LabelCellRow = S['CellRow']
export type LabelCellIn = S['CellIn']
export type LabelCellEvent = S['CellEvent']
export type LabelImportReport = S['ImportReport']
