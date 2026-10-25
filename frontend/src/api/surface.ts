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
  BrokenDerived,
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
  ItemFilter,
  ItemPage,
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
  RunAttemptControl,
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
  SourceOperation,
  SourceOperationStart,
  SourceOperationControl,
  SourceOperationEstimate,
  SourceOperationConvert,
  SourcePlanPage,
  InventoryPage,
  EstimateProgress,
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
  /** Case rollup (`CaseRollup`), sent as `curation_status` */
  status?: string
  warning?: 'any' | 'none' | ''
  voi?: 'any' | 'none' | ''
  /** `var.{name}=value` (categorical) or `var.{name}=min..max` (continuous); empty = no filter */
  vars?: Record<string, string>
  /** Include cases whose items are all excluded upstream */
  showExcluded?: boolean
  /** First N cases only (one page), e.g. for a project thumbnail */
  limit?: number
  /** Only these items ("Send to Explorer"); cases are the items' cases. Client-side: the case list has no item filter */
  itemIds?: string[]
}

/** Case of an item: `item_id` is `{case_id}.{scan_idx}.{scope}.{side}` */
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
  /** Realtime events for one project; returns the unsubscribe function */
  subscribe(pid: string, listener: (e: ServerEvent) => void, onState?: (s: ConnectionState) => void): () => void
  health(): Promise<Health>

  /** `archived`: the archived ones instead */
  listProjects(opts?: { archived?: boolean }): Promise<ProjectSummary[]>
  /** 409 `job-conflict` while a job of the project runs */
  archiveProject(pid: string): Promise<ProjectSummary>
  unarchiveProject(pid: string): Promise<Project>
  getProject(pid: string): Promise<Project>
  openDataset(path: string): Promise<Project[]>
  createProject(p: { name: string; description?: string; default_modality?: ProjectModality; dataset_root?: string }): Promise<Project>
  /** PATCH with `If-Match: etag`; a stale etag rejects with 412 `precondition-failed` */
  updateProject(pid: string, patch: ProjectPatch, etag: string): Promise<Project>
  updateLabelMap(pid: string, labels: LabelDef[], etag: string): Promise<Project>
  listPacks(): Promise<PackInfo[]>
  applyPack(pid: string, packId: string): Promise<PackApplied>
  /** View-only link: create/rotate, revoke */
  createViewToken(pid: string): Promise<ViewToken>
  revokeViewToken(pid: string): Promise<void>
  listRoots(pid: string): Promise<RootInfo[]>
  relinkRoot(pid: string, alias: string, path: string): Promise<RelinkResult>
  /** Register the project's derived folder (inside ALLOWED_DERIVED_ROOTS) */
  setDerivedRoot(pid: string, path: string, alias?: string): Promise<RelinkResult>
  /** The segmentation set shown and used when none is picked */
  setDefaultSeg(pid: string, segId: string, etag: string): Promise<Project>
  /** Project folder without `cache/`, never image data */
  exportBundle(pid: string): Promise<ProjectBundle>
  /** Multipart field `bundle`; `needs_relink` → relink dialog */
  importBundle(file: File): Promise<BundleImportResult>

  /** Candidate adapters for a folder or one file; refusals carry `actions[]` */
  detectSource(path: string): Promise<DetectResult>
  openPath(path: string): Promise<OpenSession>
  /** Header info of an Open-mode DICOM item */
  openDicomTags(sid: string, n: number): Promise<Record<string, unknown>>
  getOpen(sid: string): Promise<OpenSession>
  closeOpen(sid: string): Promise<void>
  /** Volume URL; NumPy needs `axisOrder` unless the session decided it */
  openImageUrl(sid: string, n: number, axisOrder?: AxisOrder | null): string | null
  /** Middle slice of a NumPy array in one axis order (the Open dialog) */
  openPreviewUrl(sid: string, n: number, axisOrder: AxisOrder): string | null
  /** Attach a segmentation to item n; `geometry-mismatch` when it does not fit */
  attachOpen(sid: string, n: number, path: string): Promise<OpenSession>
  /** A new .nii.gz under ALLOWED_DERIVED_ROOTS; never overwrites */
  saveOpen(sid: string, n: number, body: SaveOpenBody): Promise<SavedOpen>

  /** `role: 'derived'` browses ALLOWED_DERIVED_ROOTS */
  fsList(path: string | null, role?: RootRole): Promise<FsListing>
  importPreview(pid: string, req: PreviewRequest): Promise<ImportPreview>
  commitImport(pid: string, previewId: string): Promise<CommitResult>
  importHistory(pid: string): Promise<ImportHistory>
  listWarnings(pid: string): Promise<QCWarning[]>
  /** Full SHA-256 job; 409 `job-conflict` while one runs */
  startHashJob(pid: string, force?: boolean): Promise<HashJobStarted>

  listVariables(pid: string): Promise<Variable[]>
  patchVariable(pid: string, name: string, patch: VariablePatch): Promise<Variable>
  createDerived(pid: string, def: DerivedDef): Promise<Variable>
  deleteDerived(pid: string, name: string): Promise<void>
  /** Stored derived definitions that no longer build (e.g. a deleted label table) */
  brokenDerived(pid: string): Promise<BrokenDerived[]>
  importExternal(pid: string, file: File, key: 'case_id' | 'patient_id'): Promise<ExternalImportResult>

  listItems(pid: string, f?: ItemFilter): Promise<ItemPage>
  listItemIds(pid: string, f?: ItemFilter): Promise<string[]>
  listCases(pid: string, f?: CaseFilter): Promise<CaseSummary[]>
  getCase(pid: string, cid: string): Promise<CaseDetail>
  getItem(pid: string, iid: string): Promise<ItemDetail>
  previewRecycle(pid: string, iid: string): Promise<import('./schema').components['schemas']['RecyclePlan']>
  recycleScan(pid: string, iid: string, token: string, reviewer: string): Promise<import('./schema').components['schemas']['RecycleResult']>
  /** Thumbnail URL, or null when the binding renders thumbnails itself (mock) */
  thumbnailUrl(pid: string, iid: string): string | null

  listSegmentations(pid: string): Promise<SegmentationInfo[]>
  patchSegmentation(pid: string, segId: string, patch: SegmentationPatch): Promise<SegmentationInfo>
  /** URL of one set's mask (`seg` omitted = `default_seg`) */
  maskUrl(pid: string, iid: string, segId?: string): string | null

  /** Plugin Library; `pid` adds the project-dependent status */
  listPlugins(pid?: string): Promise<PluginList>

  /** Workspace tasks without a project; estimate = the converter dry run.
   *  `progressId` names the dry run, so `estimateProgress` can say where it is */
  estimateWorkspaceTask(taskId: string, selection: TaskSelection, settings?: Record<string, unknown>, progressId?: string): Promise<TaskEstimate>
  /** A named dry run's stage while it runs (`not-found` once it has returned) */
  estimateProgress(progressId: string): Promise<EstimateProgress>
  cancelEstimate(progressId: string): Promise<void>
  startWorkspaceRun(body: WorkspaceRunRequest): Promise<TaskRunStarted>
  listWorkspaceRuns(): Promise<WorkspaceRun[]>
  getWorkspaceRun(rid: string): Promise<WorkspaceRun>
  cancelWorkspaceRun(rid: string, body?: RunAttemptControl): Promise<WorkspaceRun>
  resumeWorkspaceRun(rid: string, body?: RunAttemptControl): Promise<TaskRunStarted>
  retryFailedWorkspaceRun(rid: string, body: RunAttemptControl): Promise<TaskRunStarted>
  startSourceOperation(body: SourceOperationStart): Promise<SourceOperation>
  listSourceOperations(): Promise<SourceOperation[]>
  getSourceOperation(id: string): Promise<SourceOperation>
  estimateSourceOperation(id: string, body: SourceOperationEstimate): Promise<SourceOperation>
  convertSourceOperation(id: string, body: SourceOperationConvert): Promise<SourceOperation>
  cancelSourceOperation(id: string, body: SourceOperationControl): Promise<SourceOperation>
  resumeSourceOperation(id: string, body: SourceOperationControl): Promise<SourceOperation>
  retryFailedSourceOperation(id: string, body: SourceOperationControl): Promise<SourceOperation>
  sourceOperationSeries(id: string, cursor?: string, limit?: number): Promise<InventoryPage>
  sourceOperationPlan(id: string, options?: { cursor?: string; limit?: number; action?: 'convert' | 'skip' }): Promise<SourcePlanPage>
  listLayers(pid: string): Promise<LayerInfo[]>
  /** `dataset_table.csv|parquet` or `dataset.jsonl`; sensitive fields only when asked */
  datasetTableUrl(pid: string, format: 'csv' | 'parquet' | 'jsonl', includeSensitive?: boolean): string

  /** `deleted`: only the deleted tables */
  listLabelTables(pid: string, deleted?: boolean): Promise<LabelTableInfo[]>
  createLabelTable(pid: string, body: LabelTableCreate): Promise<LabelTable>
  patchLabelTable(pid: string, tid: string, body: LabelTablePatch): Promise<LabelTable>
  labelCells(pid: string, tid: string): Promise<LabelCellsPage>
  writeLabelCells(pid: string, tid: string, cells: LabelCellIn[], reviewer: string): Promise<{ n_events: number }>
  labelHistory(pid: string, tid: string, target?: string, columnId?: string): Promise<LabelCellEvent[]>
  importLabelTable(pid: string, tid: string, file: File, reviewer: string): Promise<LabelImportReport>
  labelExportUrl(pid: string, tid: string, format: 'csv' | 'parquet'): string

  listTasks(): Promise<TaskList>
  getTask(taskId: string): Promise<TaskInfo>
  validateTask(taskId: string, settings: Record<string, unknown>): Promise<TaskValidateResult>
  preflightTask(pid: string, taskId: string, selection: TaskSelection, settings?: Record<string, unknown>): Promise<PreflightResult>
  estimateTask(pid: string, taskId: string, selection: TaskSelection, settings?: Record<string, unknown>, progressId?: string): Promise<TaskEstimate>
  startTaskRun(pid: string, body: TaskRunRequest, reviewer?: string): Promise<TaskRunStarted>
  /** `archived`: the archived supervised runs instead */
  listTaskRuns(pid: string, taskId?: string, archived?: boolean): Promise<TaskRunSummary[]>
  getTaskRun(pid: string, rid: string): Promise<TaskRunDetail>
  cancelTaskRun(pid: string, rid: string, body?: RunAttemptControl): Promise<TaskRunDetail>
  /** Supervised runs: `pausing` until the supervisor confirms cleanup */
  pauseTaskRun(pid: string, rid: string): Promise<TaskRunDetail>
  /** Hide an inactive supervised run; its records and masks stay */
  archiveTaskRun(pid: string, rid: string): Promise<TaskRunDetail>
  resumeTaskRun(pid: string, rid: string, body?: RunAttemptControl): Promise<TaskRunStarted>
  retryFailedTaskRun(pid: string, rid: string, body: RunAttemptControl): Promise<TaskRunStarted>
  taskRunErrors(pid: string, rid: string): Promise<TaskItemError[]>
  taskRunOutputs(pid: string, rid: string): Promise<TaskRunOutput[]>
  listAnnotations(pid: string, f?: { field?: string; run?: string; item_id?: string }): Promise<AnnotationRow[]>
  /** Activate a run for one field (`null` = none); the server reindexes */
  setAnnotationSource(pid: string, field: string, runId: string | null): Promise<AnnotationSources>
  /** The item's DICOM JSON sidecar, on demand only */
  dicomTags(pid: string, iid: string): Promise<Record<string, unknown>>
  /** The converter CLI's curation.csv, once */
  importConverterCuration(pid: string, file: File, reviewer: string): Promise<V2ImportReport>

  /** Newest first */
  listEvents(pid: string, f?: { item_id?: string; case_id?: string }): Promise<CurationEvent[]>
  appendEvent(pid: string, ev: NewCurationEvent, reviewer: string): Promise<CurationEvent>
  /** Phase selections of one scan (or all), newest first */
  phaseEvents(pid: string, f?: { case_id?: string; scan_idx?: string }): Promise<PhaseEvent[]>
  /** One-click phase selection or accepting the analyzer guess */
  appendPhase(pid: string, ev: NewPhaseEvent, reviewer: string): Promise<PhaseEvent>
  /** Write `exports/phase_selections.json` */
  exportPhase(pid: string): Promise<PhaseExport>
  curationState(pid: string): Promise<CurationStateRow[]>
  queue(pid: string): Promise<QueueRow[]>
  /** `format=csv`: the server resolves absolute paths for 3D Slicer */
  queueCsv(pid: string): Promise<Blob>
  /** Write the curation export files into the project's `exports/` */
  curationExports(pid: string): Promise<CurationExport>
  /** v2 `curation_review.csv` → events */
  importV2(pid: string, file: File, reviewer: string): Promise<V2ImportReport>

  /** Engine options, defaults, constraints */
  radiomicsSchema(): Promise<SettingsSchema>
  /** Authoritative validation; `nItems = null` skips the empty-selection check */
  validateRadiomics(settings: RadiomicsSettings, labels: number[] | null, nItems: number | null): Promise<ValidateResult>
  /** All pages */
  listProfiles(pid: string): Promise<Profile[]>
  /** Saving settings that hash to an existing profile returns that profile */
  saveProfile(pid: string, name: string, settings: RadiomicsSettings): Promise<Profile>
  renameProfile(pid: string, hash: string, name: string): Promise<Profile>
  /** Returns the remaining profiles */
  deleteProfile(pid: string, hash: string): Promise<Profile[]>
  estimate(pid: string, settings: RadiomicsSettings, selection: Selection): Promise<EstimateResult>
  /** Newest first */
  listRuns(pid: string): Promise<RunSummary[]>
  getRun(pid: string, rid: string): Promise<RunDetail>
  startRun(pid: string, body: StartRunBody, reviewer: string): Promise<RunDetail>
  cancelRun(pid: string, rid: string): Promise<RunDetail>
  resumeRun(pid: string, rid: string): Promise<RunDetail>
  /** JSON long rows (Measurements panel) */
  runFeatures(pid: string, rid: string, itemId?: string): Promise<FeatureRow[]>
  runExportUrl(pid: string, rid: string, format: RunExportFormat, shape: RunExportShape): string
  runErrors(pid: string, rid: string): Promise<RunError[]>

  dashboardView<V extends DashboardView>(pid: string, rid: string, view: V, body: ViewRequest<V>): Promise<ViewResponse<V>>
  listAnalyses(pid: string, rid?: string): Promise<AnalysisSummary[]>
  getAnalysis(pid: string, aid: string): Promise<Analysis>
  createAnalysis(pid: string, spec: AnalysisSpec, reviewer: string): Promise<Analysis>
  exportAnalysis(pid: string, aid: string, file: AnalysisExportFile): Promise<Blob>

  listJobs(pid?: string): Promise<Job[]>
  cancelJob(pid: string, jobId: string): Promise<void>
}
