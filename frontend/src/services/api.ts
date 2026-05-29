import axios from 'axios'

export const AUTH_TOKEN_STORAGE_KEY = 'radiology-ui-token'
const TOKEN_STORAGE_MODE = (import.meta.env.VITE_AUTH_TOKEN_STORAGE ?? 'memory').toLowerCase()
const USE_LOCAL_STORAGE_TOKEN = TOKEN_STORAGE_MODE === 'local'
let memoryAuthToken = ''

export type Axis = 'axial' | 'coronal' | 'sagittal'
export type SeriesType = 'nifti' | 'voi'
export type ReviewAction = 'reclassify' | 'delete'
export type PhaseDecision = 'NC' | 'ART' | 'VEN'
export type CanonicalPhase = 'NC' | 'CMP' | 'NP' | 'EXC' | 'DELAY' | 'UNK'
export type Scope = 'complete' | 'voi'
export type PathStatusValue = 'not_provided' | 'exists' | 'missing' | 'unreadable'
export type CurationTarget =
  | 'SEG'
  | 'tumor_mask'
  | 'kidney_mask'
  | 'cyst_mask'
  | 'VOI_mask'
  | 'phase_issue'
  | 'side_laterality_issue'
export type CurationStatus =
  | 'not_reviewed'
  | 'accepted'
  | 'needs_minor_correction'
  | 'needs_major_correction'
  | 'rejected'
  | 'missing'
  | 'wrong_phase_suspected'
  | 'wrong_side_suspected'
  | 'cannot_assess'
export type CurationPriority = 'low' | 'medium' | 'high'

export interface HealthStatus {
  status: string
  allow_data_mutations?: boolean
  webui_state_dir?: string
}

export interface WorkspaceStatus {
  configured: boolean
  dataset_id: string | null
  dataset_path: string | null
  database_csv_path: string | null
  workspace_dir: string | null
}

export interface DatasetBrowserRoot {
  label: string
  path: string
  source: string
  exists: boolean
  readable: boolean
}

export interface DatasetBrowserRootsResponse {
  roots: DatasetBrowserRoot[]
}

export interface DatasetBrowserEntry {
  name: string
  path: string
  type: 'directory' | 'file'
  is_database_csv: boolean
  maybe_has_dataset_structure: boolean
  readable: boolean
}

export interface DatasetBrowserListResponse {
  path: string
  parent_path: string | null
  entries: DatasetBrowserEntry[]
}

export interface WorkspaceSelectionValidationPayload {
  dataset_folder_path?: string | null
  database_csv_path?: string | null
}

export interface SelectionValidationMessage {
  code: string
  message: string
  severity: 'success' | 'warning' | 'error'
  path: string | null
}

export interface WorkspaceSelectionSummary {
  dataset_id: string | null
  dataset_root: string | null
  database_csv_path: string | null
  has_database: boolean
  row_count: number
  case_count: number
  sampled_rows: number
  sampled_referenced_files: number
  sampled_existing_files: number
  has_nifti: boolean
  has_seg: boolean
  has_voi: boolean
  has_manifest: boolean
}

export interface WorkspaceSelectionValidationResponse {
  valid: boolean
  activated: boolean
  requires_dataset_root: boolean
  summary: WorkspaceSelectionSummary
  successes: SelectionValidationMessage[]
  warnings: SelectionValidationMessage[]
  errors: SelectionValidationMessage[]
  workspace: WorkspaceStatus | null
}

export interface DatasetSummary {
  dataset_id: string
  patient_count: number
  has_nifti: boolean
  has_seg: boolean
  has_voi: boolean
  has_manifest: boolean
}

export interface PatientSummary {
  patient_id: string
  source_patient_id: string | null
  group: string | null
  phases: string[]
  series_count: number
  seg_count: number
  voi_count: number
  has_deleted: boolean
  deleted_series_count: number
}

export interface SeriesInfo {
  series_id: string
  patient_id: string
  type: SeriesType
  group: string | null
  phase: string | null
  laterality: string | null
  filename: string
  has_seg: boolean
  deleted: boolean
  storage_path: string | null
}

export interface VolumeInfo {
  series_id: string
  load_handle: string
  shape: number[]
  spacing: number[]
  has_mask: boolean
  labels: number[]
}

export interface PathStatus {
  raw: string | null
  resolved: string | null
  status: PathStatusValue
}

export interface QCWarning {
  code: string
  message: string
  severity: 'info' | 'warning' | 'error'
  row_id: string | null
  scope: Scope | null
  path_field: string | null
}

export interface CaseSummary {
  case_id: string
  patient_id: string | null
  group: string | null
  available_phases: CanonicalPhase[]
  scan_count: number
  seg_count: number
  voi_image_count: number
  voi_mask_count: number
  voi_sides: string[]
  latest_curation_status: string | null
  warning_count: number
  has_comments: boolean
}

export interface CaseInventoryRow {
  row_id: string
  source_row_id: string | null
  case_id: string
  patient_id: string | null
  group: string | null
  raw_phase: string | null
  canonical_phase: CanonicalPhase
  phase_status: 'normalized' | 'ambiguous' | 'missing'
  scan_idx: string | null
  side: string | null
  scope_availability: Record<Scope, boolean>
  nifti_path: PathStatus
  seg_path: PathStatus
  voi_image_path: PathStatus
  voi_mask_path: PathStatus
  has_seg: boolean
  has_voi_image: boolean
  has_voi_mask: boolean
  qc_warnings: QCWarning[]
  latest_curation_status: string | null
}

export interface CaseDossier {
  case_id: string
  core: Record<string, unknown>
  acquisition: Record<string, unknown>
  segmentation_voi: Record<string, unknown>
  preprocessing_qc: Record<string, unknown>
  external_research: Record<string, unknown>
  advanced_raw_fields: Array<Record<string, unknown>>
}

export interface RequiredColumnStatus {
  name: string
  present: boolean
  alternatives: string[]
}

export interface DatabaseValidationReport {
  dataset_id: string
  has_database: boolean
  row_count: number
  case_count: number
  required_columns: RequiredColumnStatus[]
  warnings: QCWarning[]
}

export interface CurationDecisionRequest {
  case_id: string
  row_id?: string | null
  scope: Scope
  target: CurationTarget
  status: CurationStatus
  priority: CurationPriority
  comment: string
  proposed_phase?: string | null
  reviewer: string
  add_to_queue?: boolean
}

export interface CurationDecision extends CurationDecisionRequest {
  review_id: string
  dataset_id: string
  patient_id: string | null
  source_row_id: string | null
  scan_idx: string | null
  raw_phase: string | null
  canonical_phase: string | null
  side: string | null
  reviewed_at: string
  nifti_path: string | null
  seg_path: string | null
  voi_image_path: string | null
  voi_mask_path: string | null
}

export interface CorrectionQueueResponse {
  dataset_id: string
  items: CurationDecision[]
}

export interface PhaseCorrectionRequest {
  case_id: string
  scan_idx?: string | null
  proposed_phase: string
  comment?: string
  reviewer?: string
  add_to_queue?: boolean
}

export interface PhaseCorrectionResponse {
  case_id: string
  scan_idx: string | null
  proposed_phase: string
  total_rows: number
  complete_rows: number
  voi_rows: number
  decisions: CurationDecision[]
}

export interface DatasetViewerSettings {
  last_patient: string | null
  last_series: string | null
  ww: number | null
  wl: number | null
  layers_visible: number[]
  layers_opacity: Record<string, number>
}

export type ViewerSettings = Record<string, DatasetViewerSettings>

export interface SliceQuery {
  load_handle?: string
  ww?: number
  wl?: number
  layers?: number[]
  opacity_1?: number
  opacity_2?: number
  opacity_3?: number
}

export interface ReviewOperation {
  patient_id: string
  series_id: string
  action: ReviewAction
  target_phase?: PhaseDecision
}

export interface ReviewApplyPayload {
  operations: ReviewOperation[]
}

export interface ReviewApplyResult {
  patient_id: string
  series_id: string
  action: ReviewAction
  target_phase: PhaseDecision | null
  status: 'applied' | 'skipped' | 'failed'
  message: string
  moved_files: ReviewMovedFile[]
  manifest_updated: boolean
}

export interface ReviewApplyResponse {
  batch_id: string
  applied_at: string
  summary: {
    requested: number
    applied: number
    skipped: number
    failed: number
  }
  results: ReviewApplyResult[]
}

export interface ReviewMovedFile {
  source: string
  destination: string
}

export interface ReviewDeleteDecision {
  decision_id: string
  applied_at: string
  patient_id: string
  series_id: string
  filename: string | null
  series_type: string | null
  moved_files: ReviewMovedFile[]
}

interface RequestOptions {
  signal?: AbortSignal
}

type AuthPromptHandler = () => Promise<string | null>

interface RetryableRequestConfig {
  _authRetried?: boolean
}

const api = axios.create({
  baseURL: '/api',
})

let authPromptHandler: AuthPromptHandler | null = null
let pendingPrompt: Promise<string | null> | null = null

api.interceptors.request.use((config) => {
  const token = getStoredAuthToken()
  if (!token) {
    return config
  }

  config.headers = config.headers ?? {}
  config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (!axios.isAxiosError(error) || error.response?.status !== 401 || !error.config) {
      return Promise.reject(error)
    }

    const requestConfig = error.config as typeof error.config & RetryableRequestConfig
    if (requestConfig._authRetried) {
      return Promise.reject(error)
    }

    const token = await requestAuthToken()
    if (!token) {
      return Promise.reject(error)
    }

    setStoredAuthToken(token)
    requestConfig._authRetried = true
    requestConfig.headers = requestConfig.headers ?? {}
    requestConfig.headers.Authorization = `Bearer ${token}`
    return api.request(requestConfig)
  },
)

export function getStoredAuthToken(): string {
  if (USE_LOCAL_STORAGE_TOKEN) {
    return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) ?? ''
  }
  return memoryAuthToken
}

export function setStoredAuthToken(token: string): void {
  memoryAuthToken = token
  if (!USE_LOCAL_STORAGE_TOKEN) {
    window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY)
    return
  }

  if (token) {
    window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token)
  } else {
    window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY)
  }
}

export function registerAuthPromptHandler(handler: AuthPromptHandler | null): void {
  authPromptHandler = handler
}

export function getApiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data
    if (typeof detail === 'string') {
      return detail
    }
    if (
      detail &&
      typeof detail === 'object' &&
      'detail' in detail &&
      typeof detail.detail === 'string'
    ) {
      return detail.detail
    }
    if (error.message) {
      return error.message
    }
  }

  if (error instanceof Error && error.message) {
    return error.message
  }

  return 'Unexpected API error'
}

export function isHandleExpiredError(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 410
}

async function requestAuthToken(): Promise<string | null> {
  if (!authPromptHandler) {
    return null
  }
  if (!pendingPrompt) {
    pendingPrompt = authPromptHandler().finally(() => {
      pendingPrompt = null
    })
  }
  return pendingPrompt
}

function buildSliceQuery(query: SliceQuery): string {
  const params = new URLSearchParams()

  if (query.load_handle) {
    params.set('load_handle', query.load_handle)
  }
  if (typeof query.ww === 'number') {
    params.set('ww', String(query.ww))
  }
  if (typeof query.wl === 'number') {
    params.set('wl', String(query.wl))
  }
  if (query.layers) {
    params.set('layers', query.layers.join(','))
  }

  ;(['opacity_1', 'opacity_2', 'opacity_3'] as const).forEach((key) => {
    const value = query[key]
    if (typeof value === 'number') {
      params.set(key, String(value))
    }
  })

  const queryString = params.toString()
  return queryString ? `?${queryString}` : ''
}

export const apiClient = {
  async getHealth(): Promise<HealthStatus> {
    const response = await api.get<HealthStatus>('/health')
    return response.data
  },

  async getWorkspace(): Promise<WorkspaceStatus> {
    const response = await api.get<WorkspaceStatus>('/workspace')
    return response.data
  },

  async putWorkspace(datasetPath: string, databaseCsvPath?: string | null): Promise<WorkspaceStatus> {
    const response = await api.put<WorkspaceStatus>('/workspace', {
      dataset_path: datasetPath,
      database_csv_path: databaseCsvPath ?? null,
    })
    return response.data
  },

  async clearWorkspace(): Promise<WorkspaceStatus> {
    const response = await api.delete<WorkspaceStatus>('/workspace')
    return response.data
  },

  async listDatasetBrowserRoots(): Promise<DatasetBrowserRootsResponse> {
    const response = await api.get<DatasetBrowserRootsResponse>('/dataset-browser/roots')
    return response.data
  },

  async listDatasetBrowserPath(path: string): Promise<DatasetBrowserListResponse> {
    const response = await api.get<DatasetBrowserListResponse>('/dataset-browser/list', {
      params: { path },
    })
    return response.data
  },

  async validateWorkspaceSelection(
    payload: WorkspaceSelectionValidationPayload,
  ): Promise<WorkspaceSelectionValidationResponse> {
    const response = await api.post<WorkspaceSelectionValidationResponse>(
      '/workspace/validate-selection',
      payload,
    )
    return response.data
  },

  async listDatasets(): Promise<DatasetSummary[]> {
    const response = await api.get<DatasetSummary[]>('/datasets')
    return response.data
  },

  async listPatients(datasetId: string): Promise<PatientSummary[]> {
    const response = await api.get<PatientSummary[]>(`/datasets/${datasetId}/patients`)
    return response.data
  },

  async getDatabaseValidation(datasetId: string): Promise<DatabaseValidationReport> {
    const response = await api.get<DatabaseValidationReport>(
      `/datasets/${datasetId}/database/validation`,
    )
    return response.data
  },

  async listCases(datasetId: string): Promise<CaseSummary[]> {
    const response = await api.get<CaseSummary[]>(`/datasets/${datasetId}/cases`)
    return response.data
  },

  async listCaseInventory(datasetId: string, caseId: string): Promise<CaseInventoryRow[]> {
    const response = await api.get<CaseInventoryRow[]>(
      `/datasets/${datasetId}/cases/${caseId}/inventory`,
    )
    return response.data
  },

  async getCaseDossier(datasetId: string, caseId: string): Promise<CaseDossier> {
    const response = await api.get<CaseDossier>(
      `/datasets/${datasetId}/cases/${caseId}/dossier`,
    )
    return response.data
  },

  async loadCaseSource(
    datasetId: string,
    caseId: string,
    rowId: string,
    scope: Scope,
    options: RequestOptions = {},
  ): Promise<VolumeInfo> {
    const params = new URLSearchParams({
      row_id: rowId,
      scope,
    })
    const response = await api.post<VolumeInfo>(
      `/datasets/${datasetId}/cases/${caseId}/load?${params.toString()}`,
      undefined,
      {
        signal: options.signal,
      },
    )
    return response.data
  },

  async getCurationHistory(datasetId: string, caseId: string): Promise<CurationDecision[]> {
    const response = await api.get<CurationDecision[]>(
      `/datasets/${datasetId}/curation/cases/${caseId}/history`,
    )
    return response.data
  },

  async saveCurationDecision(
    datasetId: string,
    payload: CurationDecisionRequest,
  ): Promise<CurationDecision> {
    const response = await api.post<CurationDecision>(
      `/datasets/${datasetId}/curation/decisions`,
      payload,
    )
    return response.data
  },

  async savePhaseCorrectionByScan(
    datasetId: string,
    payload: PhaseCorrectionRequest,
  ): Promise<PhaseCorrectionResponse> {
    const response = await api.post<PhaseCorrectionResponse>(
      `/datasets/${datasetId}/curation/phase-correction`,
      payload,
    )
    return response.data
  },

  async listCorrectionQueue(datasetId: string): Promise<CorrectionQueueResponse> {
    const response = await api.get<CorrectionQueueResponse>(
      `/datasets/${datasetId}/curation/correction-queue`,
    )
    return response.data
  },

  async listSeries(datasetId: string, patientId: string): Promise<SeriesInfo[]> {
    const response = await api.get<SeriesInfo[]>(
      `/datasets/${datasetId}/patients/${patientId}/series`,
    )
    return response.data
  },

  async loadSeries(
    datasetId: string,
    patientId: string,
    seriesId: string,
    storagePath?: string | null,
    options: RequestOptions = {},
  ): Promise<VolumeInfo> {
    const params = new URLSearchParams()
    if (storagePath) {
      params.set('storage_path', storagePath)
    }
    const response = await api.post<VolumeInfo>(
      `/datasets/${datasetId}/patients/${patientId}/series/${seriesId}/load${
        params.size > 0 ? `?${params.toString()}` : ''
      }`,
      undefined,
      {
        signal: options.signal,
      },
    )
    return response.data
  },

  async getSliceBlob(
    axis: Axis,
    index: number,
    query: SliceQuery = {},
    options: RequestOptions = {},
  ): Promise<Blob> {
    const response = await api.get<Blob>(`/slice/${axis}/${index}${buildSliceQuery(query)}`, {
      responseType: 'blob',
      signal: options.signal,
    })
    return response.data
  },

  async getMeshBlob(
    label: number,
    loadHandle: string,
    smooth = true,
    options: RequestOptions = {},
  ): Promise<Blob> {
    const params = new URLSearchParams({
      load_handle: loadHandle,
      smooth: String(smooth),
    })
    const response = await api.get<Blob>(`/mesh/${label}?${params.toString()}`, {
      responseType: 'blob',
      signal: options.signal,
    })
    return response.data
  },

  sliceUrl(axis: Axis, index: number, query: SliceQuery = {}): string {
    return `/api/slice/${axis}/${index}${buildSliceQuery(query)}`
  },

  meshUrl(label: number, loadHandle: string, smooth = true): string {
    const params = new URLSearchParams({
      load_handle: loadHandle,
      smooth: String(smooth),
    })
    return `/api/mesh/${label}?${params.toString()}`
  },

  async getSettings(): Promise<ViewerSettings> {
    const response = await api.get<ViewerSettings>('/settings')
    return response.data
  },

  async putSettings(settings: ViewerSettings): Promise<ViewerSettings> {
    const response = await api.put<ViewerSettings>('/settings', settings)
    return response.data
  },

  async applyReviewOperations(
    datasetId: string,
    payload: ReviewApplyPayload,
  ): Promise<ReviewApplyResponse> {
    const response = await api.post<ReviewApplyResponse>(
      `/datasets/${datasetId}/review/apply`,
      payload,
    )
    return response.data
  },

  async listDeleteDecisions(datasetId: string): Promise<ReviewDeleteDecision[]> {
    const response = await api.get<ReviewDeleteDecision[]>(
      `/datasets/${datasetId}/review/deletions`,
    )
    return response.data
  },

  async undoDeleteDecision(
    datasetId: string,
    decisionId: string,
  ): Promise<ReviewApplyResponse> {
    const response = await api.post<ReviewApplyResponse>(
      `/datasets/${datasetId}/review/undo-delete/${decisionId}`,
    )
    return response.data
  },
}
