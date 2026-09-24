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
  Estimate,
  ExternalImportResult,
  FeatureRow,
  FsListing,
  Health,
  ImportHistory,
  ImportPreview,
  Issue,
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
  RadiomicsRun,
  RelinkResult,
  RootInfo,
  RunError,
  ServerEvent,
  Settings,
  SettingsSchema,
  V2ImportReport,
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
  schema(): Promise<SettingsSchema>
  validate(settings: Settings, selection: { labels: number[]; items: number }): Promise<Issue[]>
  estimate(pid: string, selection: { scope: string; labels: number[] }): Promise<Estimate>
  listProfiles(pid: string): Promise<Profile[]>
  saveProfile(pid: string, name: string, settings: Settings): Promise<{ name: string; hash: string }>
  listRuns(pid: string): Promise<RadiomicsRun[]>
  getRun(pid: string, rid: string): Promise<RadiomicsRun>
  startRun(
    pid: string,
    name: string,
    selection: { scope: 'complete' | 'voi'; labels: number[] },
    reviewer: string,
  ): Promise<{ run_id: string; job_id: string }>
  runFeatures(pid: string, rid: string, itemId?: string): Promise<FeatureRow[]>
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
