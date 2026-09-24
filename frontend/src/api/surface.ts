// The API surface every backend binding implements: the HTTP client (default) and the in-memory
// mock (VITE_API_MODE=mock, the standalone prototype and unit tests). Hooks only see this interface.
import type {
  Analysis,
  AnalysisExportFile,
  AnalysisSpec,
  AnalysisSummary,
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
  Health,
  ImportHistory,
  ImportPreview,
  ItemDetail,
  Job,
  LabelDef,
  NewCurationEvent,
  Preset,
  PreviewRequest,
  Profile,
  Project,
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
  ServerEvent,
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
  createProject(p: { name: string; description?: string; preset: Preset }): Promise<Project>
  updateLabelMap(pid: string, labels: LabelDef[]): Promise<Project>
  listRoots(pid: string): Promise<RootInfo[]>
  relinkRoot(pid: string, alias: string, path: string): Promise<RelinkResult>

  // Import (API-10..14)
  fsList(path: string | null): Promise<FsListing>
  importPreview(pid: string, req: PreviewRequest): Promise<ImportPreview>
  commitImport(pid: string, previewId: string): Promise<CommitResult>
  importHistory(pid: string): Promise<ImportHistory>
  listWarnings(pid: string): Promise<QCWarning[]>

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

  // Curation (API-50..54)
  /** Newest first (CUR-14) */
  listEvents(pid: string, f?: { item_id?: string; case_id?: string }): Promise<CurationEvent[]>
  appendEvent(pid: string, ev: NewCurationEvent, reviewer: string): Promise<CurationEvent>
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
