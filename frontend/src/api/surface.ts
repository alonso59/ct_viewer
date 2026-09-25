// The API surface every backend binding implements: the HTTP client (default) and the in-memory
// mock (VITE_API_MODE=mock, the standalone prototype and unit tests). Hooks only see this interface.
import type {
  Analysis,
  AnalysisExportFile,
  AnalysisSpec,
  AnalysisSummary,
  BundleImportResult,
  CaseDetail,
  CaseSummary,
  CommitResult,
  CurationEvent,
  CurationExport,
  CurationStateRow,
  DashboardView,
  DerivedDef,
  EstimateResult,
  ExternalImportResult,
  FeatureRow,
  FsListing,
  HashJobStarted,
  Health,
  ImportHistory,
  ImportPreview,
  ItemDetail,
  Job,
  LabelDef,
  NewCurationEvent,
  PackApplied,
  PackInfo,
  ProjectModality,
  ProjectPatch,
  ViewToken,
  PreviewRequest,
  Profile,
  Project,
  ProjectBundle,
  ProjectSummary,
  QCWarning,
  QueueRow,
  RadiomicsSettings,
  RelinkResult,
  RootInfo,
  RunDetail,
  RunError,
  RunExportFormat,
  RunExportShape,
  RunSummary,
  Selection,
  AnnotationRow,
  AnnotationSources,
  AxisOrder,
  SaveOpenBody,
  SavedOpen,
  DetectResult,
  OpenSession,
  PreflightResult,
  RootRole,
  SegmentationInfo,
  SegmentationPatch,
  ServerEvent,
  PluginList,
  LabelCellEvent,
  LabelCellIn,
  LabelCellsPage,
  LabelImportReport,
  LabelTable,
  LabelTableCreate,
  LabelTableInfo,
  LabelTablePatch,
  NewPhaseEvent,
  PhaseEvent,
  PhaseExport,
  LayerInfo,
  WorkspaceRun,
  WorkspaceRunRequest,
  TaskEstimate,
  TaskInfo,
  TaskItemError,
  TaskList,
  TaskRunDetail,
  TaskRunOutput,
  TaskRunRequest,
  TaskRunStarted,
  TaskRunSummary,
  TaskSelection,
  TaskValidateResult,
  SettingsSchema,
  StartRunBody,
  V2ImportReport,
  ValidateResult,
  Variable,
  VariablePatch,
  ViewRequest,
  ViewResponse,
} from './types'

export interface CaseFilter {
  q?: string
  phase?: string
  status?: string
  warning?: 'any' | 'none' | ''
  voi?: 'any' | 'none' | ''
  /** `var.{name}=value` (categorical) or `var.{name}=min..max` (continuous); empty = no filter */
  vars?: Record<string, string>
  /** Include cases whose items are all excluded upstream (the P1 server never lists them) */
  showExcluded?: boolean
  /** First N cases only (one page), e.g. for a project thumbnail */
  limit?: number
  /** Only these items (DB-04 "Send to Explorer"); cases are the items' cases. Client-side: API-20 has no item filter */
  itemIds?: string[]
}

/** Case of an item: `item_id` is `{case_id}.{scan_idx}.{scope}.{side}` (DATA_MODEL §item_id) */
export const caseOfItem = (itemId: string): string => itemId.split('.').slice(0, -3).join('.') || itemId

/** Cases holding at least one of `itemIds`, in list order; no list = all */
export function filterByItems<C extends { case_id: string }>(cases: C[], itemIds: string[] | undefined): C[] {
  if (!itemIds) return cases
  const wanted = new Set(itemIds.map(caseOfItem))
  return cases.filter((c) => wanted.has(c.case_id))
}

export type ConnectionState = 'connecting' | 'live' | 'offline'

export interface Api {
  readonly mode: 'http' | 'mock'
  readonly sessionId: string
  /** API-40: realtime events for one project; returns the unsubscribe function */
  subscribe(pid: string, listener: (e: ServerEvent) => void, onState?: (s: ConnectionState) => void): () => void
  health(): Promise<Health>

  // Projects (API-02..05)
  listProjects(): Promise<ProjectSummary[]>
  getProject(pid: string): Promise<Project>
  /** PRJ-14: neutral; a name and an optional default modality */
  createProject(p: { name: string; description?: string; default_modality?: ProjectModality }): Promise<Project>
  /** API-03 PATCH with `If-Match: etag` (PRJ-15); a stale etag rejects with 412 `precondition-failed` */
  updateProject(pid: string, patch: ProjectPatch, etag: string): Promise<Project>
  updateLabelMap(pid: string, labels: LabelDef[], etag: string): Promise<Project>
  /** API-28 (PRJ-16) */
  listPacks(): Promise<PackInfo[]>
  applyPack(pid: string, packId: string): Promise<PackApplied>
  /** API-61 (PRJ-17): create/rotate, revoke */
  createViewToken(pid: string): Promise<ViewToken>
  revokeViewToken(pid: string): Promise<void>
  listRoots(pid: string): Promise<RootInfo[]>
  relinkRoot(pid: string, alias: string, path: string): Promise<RelinkResult>
  /** PRJ-13: register the project's derived folder (inside ALLOWED_DERIVED_ROOTS; ADR-0014) */
  setDerivedRoot(pid: string, path: string, alias?: string): Promise<RelinkResult>
  /** ADR-0015: the set shown and used when none is picked (API-03) */
  setDefaultSeg(pid: string, segId: string, etag: string): Promise<Project>
  /** API-06 export (PRJ-08): project folder without `cache/`, never image data */
  exportBundle(pid: string): Promise<ProjectBundle>
  /** API-06 import (PRJ-09): multipart field `bundle`; `needs_relink` → relink dialog (PRJ-05) */
  importBundle(file: File): Promise<BundleImportResult>

  // Sources and Open mode (API-19, API-07/08; SRC-*)
  /** API-19: candidate adapters for a folder or one file; refusals carry `actions[]` */
  detectSource(path: string): Promise<DetectResult>
  openPath(path: string): Promise<OpenSession>
  /** VW-22 header info of an Open-mode DICOM item */
  openDicomTags(sid: string, n: number): Promise<Record<string, unknown>>
  getOpen(sid: string): Promise<OpenSession>
  closeOpen(sid: string): Promise<void>
  /** Volume URL; NumPy needs `axisOrder` unless the session decided it (SRC-12) */
  openImageUrl(sid: string, n: number, axisOrder?: AxisOrder | null): string | null
  /** Middle slice of a NumPy array in one axis order (the Open dialog) */
  openPreviewUrl(sid: string, n: number, axisOrder: AxisOrder): string | null
  /** SRC-10: attach a segmentation to item n; `geometry-mismatch` when it does not fit */
  attachOpen(sid: string, n: number, path: string): Promise<OpenSession>
  /** API-09 (SRC-14): a new .nii.gz under ALLOWED_DERIVED_ROOTS; never overwrites */
  saveOpen(sid: string, n: number, body: SaveOpenBody): Promise<SavedOpen>

  // Import (API-10..14)
  /** `role: 'derived'` browses ALLOWED_DERIVED_ROOTS (PRJ-13) */
  fsList(path: string | null, role?: RootRole): Promise<FsListing>
  importPreview(pid: string, req: PreviewRequest): Promise<ImportPreview>
  commitImport(pid: string, previewId: string): Promise<CommitResult>
  importHistory(pid: string): Promise<ImportHistory>
  listWarnings(pid: string): Promise<QCWarning[]>
  /** API-15 (IMP-09): full SHA-256 job; 409 `job-conflict` while one runs */
  startHashJob(pid: string, force?: boolean): Promise<HashJobStarted>

  // Variables (API-16..18)
  listVariables(pid: string): Promise<Variable[]>
  patchVariable(pid: string, name: string, patch: VariablePatch): Promise<Variable>
  createDerived(pid: string, def: DerivedDef): Promise<Variable>
  deleteDerived(pid: string, name: string): Promise<void>
  importExternal(pid: string, file: File, key: 'case_id' | 'patient_id'): Promise<ExternalImportResult>

  // Cases and items (API-20..26)
  listCases(pid: string, f?: CaseFilter): Promise<CaseSummary[]>
  getCase(pid: string, cid: string): Promise<CaseDetail>
  getItem(pid: string, iid: string): Promise<ItemDetail>
  /** API-26 URL, or null when the binding renders thumbnails itself (mock) */
  thumbnailUrl(pid: string, iid: string): string | null

  // Segmentation sets (API-24/27, ADR-0015)
  listSegmentations(pid: string): Promise<SegmentationInfo[]>
  patchSegmentation(pid: string, segId: string, patch: SegmentationPatch): Promise<SegmentationInfo>
  /** API-24 URL of one set's mask (`seg` omitted = `default_seg`) */
  maskUrl(pid: string, iid: string, segId?: string): string | null

  /** API-49 Plugin Library (PLG-05/06); `pid` adds the project-dependent status */
  listPlugins(pid?: string): Promise<PluginList>

  /** API-62 (TSK-13): workspace tasks without a project; estimate = the converter dry run */
  estimateWorkspaceTask(taskId: string, selection: TaskSelection, settings?: Record<string, unknown>): Promise<TaskEstimate>
  startWorkspaceRun(body: WorkspaceRunRequest): Promise<TaskRunStarted>
  listWorkspaceRuns(): Promise<WorkspaceRun[]>
  getWorkspaceRun(rid: string): Promise<WorkspaceRun>
  cancelWorkspaceRun(rid: string): Promise<WorkspaceRun>
  /** API-59 (ADR-0020): active layers and the dataset table download URL */
  listLayers(pid: string): Promise<LayerInfo[]>
  datasetTableUrl(pid: string, format: 'csv' | 'parquet'): string

  /** API-56..58 Labeling table plugin (LBL-*) */
  /** `deleted`: only the deleted tables (LBL-10) */
  listLabelTables(pid: string, deleted?: boolean): Promise<LabelTableInfo[]>
  createLabelTable(pid: string, body: LabelTableCreate): Promise<LabelTable>
  patchLabelTable(pid: string, tid: string, body: LabelTablePatch): Promise<LabelTable>
  labelCells(pid: string, tid: string): Promise<LabelCellsPage>
  writeLabelCells(pid: string, tid: string, cells: LabelCellIn[], reviewer: string): Promise<{ n_events: number }>
  labelHistory(pid: string, tid: string, target?: string, columnId?: string): Promise<LabelCellEvent[]>
  importLabelTable(pid: string, tid: string, file: File, reviewer: string): Promise<LabelImportReport>
  labelExportUrl(pid: string, tid: string, format: 'csv' | 'parquet'): string

  // Tasks (API-42..47, TSK-*)
  listTasks(): Promise<TaskList>
  getTask(taskId: string): Promise<TaskInfo>
  validateTask(taskId: string, settings: Record<string, unknown>): Promise<TaskValidateResult>
  preflightTask(pid: string, taskId: string, selection: TaskSelection, settings?: Record<string, unknown>): Promise<PreflightResult>
  estimateTask(pid: string, taskId: string, selection: TaskSelection, settings?: Record<string, unknown>): Promise<TaskEstimate>
  startTaskRun(pid: string, body: TaskRunRequest, reviewer?: string): Promise<TaskRunStarted>
  listTaskRuns(pid: string, taskId?: string): Promise<TaskRunSummary[]>
  getTaskRun(pid: string, rid: string): Promise<TaskRunDetail>
  cancelTaskRun(pid: string, rid: string): Promise<TaskRunDetail>
  resumeTaskRun(pid: string, rid: string): Promise<TaskRunStarted>
  taskRunErrors(pid: string, rid: string): Promise<TaskItemError[]>
  taskRunOutputs(pid: string, rid: string): Promise<TaskRunOutput[]>
  /** API-48 (ANZ-01/04) */
  listAnnotations(pid: string, f?: { field?: string; run?: string; item_id?: string }): Promise<AnnotationRow[]>
  /** Activate a run for one field (`null` = none); the server reindexes */
  setAnnotationSource(pid: string, field: string, runId: string | null): Promise<AnnotationSources>
  /** DCM-04/05: the item's DICOM JSON sidecar, on demand only */
  dicomTags(pid: string, iid: string): Promise<Record<string, unknown>>
  /** API-55 (CUR-15): the converter CLI's curation.csv, once */
  importConverterCuration(pid: string, file: File, reviewer: string): Promise<V2ImportReport>

  // Curation (API-50..54)
  /** Newest first (CUR-14) */
  listEvents(pid: string, f?: { item_id?: string; case_id?: string }): Promise<CurationEvent[]>
  appendEvent(pid: string, ev: NewCurationEvent, reviewer: string): Promise<CurationEvent>
  /** API-63: phase selections of one scan (or all), newest first (PHS-07) */
  phaseEvents(pid: string, f?: { case_id?: string; scan_idx?: string }): Promise<PhaseEvent[]>
  /** API-63: one-click phase selection (PHS-01) or accepting the analyzer guess (PHS-04) */
  appendPhase(pid: string, ev: NewPhaseEvent, reviewer: string): Promise<PhaseEvent>
  /** API-65: write `exports/phase_selections.json` (PHS-06) */
  exportPhase(pid: string): Promise<PhaseExport>
  curationState(pid: string): Promise<CurationStateRow[]>
  queue(pid: string): Promise<QueueRow[]>
  /** API-52 `format=csv`: the server resolves absolute paths for 3D Slicer (CUR-09) */
  queueCsv(pid: string): Promise<Blob>
  /** API-53: write CUR-10 files into the project's `exports/` */
  curationExports(pid: string): Promise<CurationExport>
  /** API-54: v2 `curation_review.csv` → events (CUR-13) */
  importV2(pid: string, file: File, reviewer: string): Promise<V2ImportReport>

  // Radiomics (API-30..37)
  /** API-30: engine options, defaults, constraints (RAD-01) */
  radiomicsSchema(): Promise<SettingsSchema>
  /** API-31: authoritative validation (RAD-04); `nItems = null` skips the empty-selection check */
  validateRadiomics(settings: RadiomicsSettings, labels: number[] | null, nItems: number | null): Promise<ValidateResult>
  /** API-32 (RAD-03); all pages */
  listProfiles(pid: string): Promise<Profile[]>
  /** Saving settings that hash to an existing profile returns that profile */
  saveProfile(pid: string, name: string, settings: RadiomicsSettings): Promise<Profile>
  renameProfile(pid: string, hash: string, name: string): Promise<Profile>
  /** Returns the remaining profiles */
  deleteProfile(pid: string, hash: string): Promise<Profile[]>
  /** API-33 (RAD-11) */
  estimate(pid: string, settings: RadiomicsSettings, selection: Selection): Promise<EstimateResult>
  /** API-34; all pages, newest first */
  listRuns(pid: string): Promise<RunSummary[]>
  getRun(pid: string, rid: string): Promise<RunDetail>
  startRun(pid: string, body: StartRunBody, reviewer: string): Promise<RunDetail>
  /** API-35 (RAD-06/08) */
  cancelRun(pid: string, rid: string): Promise<RunDetail>
  resumeRun(pid: string, rid: string): Promise<RunDetail>
  /** API-36 JSON long rows (Measurements panel, UI-14) */
  runFeatures(pid: string, rid: string, itemId?: string): Promise<FeatureRow[]>
  /** API-36 file download URL (RAD-10) */
  runExportUrl(pid: string, rid: string, format: RunExportFormat, shape: RunExportShape): string
  /** API-37 (RAD-07); all pages */
  runErrors(pid: string, rid: string): Promise<RunError[]>

  // Dashboard (API-38) and guided analysis (API-39)
  dashboardView<V extends DashboardView>(pid: string, rid: string, view: V, body: ViewRequest<V>): Promise<ViewResponse<V>>
  listAnalyses(pid: string, rid?: string): Promise<AnalysisSummary[]>
  getAnalysis(pid: string, aid: string): Promise<Analysis>
  createAnalysis(pid: string, spec: AnalysisSpec, reviewer: string): Promise<Analysis>
  exportAnalysis(pid: string, aid: string, file: AnalysisExportFile): Promise<Blob>

  // Jobs (API-41)
  listJobs(pid?: string): Promise<Job[]>
  cancelJob(pid: string, jobId: string): Promise<void>

  /** Mock only: reset demo data (Settings) and the simulated second reviewer (UI_SHELL §Prototype) */
  reset(): void
  setReviewerSimulation(pid: string | null, on: boolean): void
}
