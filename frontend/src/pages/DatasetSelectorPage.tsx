import { useEffect, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useNavigate } from 'react-router-dom'

import BackendFileBrowserDialog from '../components/dataset-setup/BackendFileBrowserDialog'
import ValidationProgressDialog from '../components/dataset-setup/ValidationProgressDialog'
import { useSettings } from '../hooks/useSettings'
import {
  apiClient,
  type CaseSummary,
  type DatabaseValidationReport,
  type DatasetSummary,
  type WorkspaceSelectionValidationPayload,
  type WorkspaceSelectionValidationResponse,
  type WorkspaceStatus,
  getApiErrorMessage,
} from '../services/api'

interface DatasetSelectorPageProps {
  workspace: WorkspaceStatus
  workspaceLoading: boolean
  workspaceError: string | null
  onWorkspaceChange: (workspace: WorkspaceStatus) => void
}

const VALIDATION_STEPS = [
  'Checking path',
  'Finding database.csv',
  'Reading CSV',
  'Checking columns',
  'Sampling files',
  'Building summary',
]

function DatasetSelectorPage({
  workspace,
  workspaceLoading,
  workspaceError,
  onWorkspaceChange,
}: DatasetSelectorPageProps) {
  const navigate = useNavigate()
  const settingsState = useSettings({ enabled: workspace.configured })
  const validationTimerRef = useRef<number | null>(null)
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pathInput, setPathInput] = useState(workspace.dataset_path ?? '')
  const [submitState, setSubmitState] = useState<{
    running: boolean
    error: string | null
  }>({
    running: false,
    error: null,
  })
  const [browserOpen, setBrowserOpen] = useState(false)
  const [lastValidation, setLastValidation] =
    useState<WorkspaceSelectionValidationResponse | null>(null)
  const [validationDialog, setValidationDialog] = useState<{
    open: boolean
    progress: number
    currentStep: string
    result: WorkspaceSelectionValidationResponse | null
    error: string | null
  }>({
    open: false,
    progress: 0,
    currentStep: VALIDATION_STEPS[0],
    result: null,
    error: null,
  })
  const [reviewReadiness, setReviewReadiness] = useState<{
    datasetId: string | null
    cases: CaseSummary[]
    validation: DatabaseValidationReport | null
    error: string | null
  }>({
    datasetId: null,
    cases: [],
    validation: null,
    error: null,
  })

  useEffect(() => {
    setPathInput(workspace.dataset_path ?? '')
  }, [workspace.dataset_path])

  useEffect(() => {
    return () => {
      clearValidationTimer()
    }
  }, [])

  useEffect(() => {
    if (!workspace.configured) {
      setDatasets([])
      setLoading(false)
      setError(null)
      return
    }

    let active = true
    setLoading(true)

    apiClient
      .listDatasets()
      .then((response) => {
        if (!active) {
          return
        }
        setDatasets(response)
        setError(null)
      })
      .catch((requestError) => {
        if (!active) {
          return
        }
        setDatasets([])
        setError(getApiErrorMessage(requestError))
      })
      .finally(() => {
        if (active) {
          setLoading(false)
        }
      })

    return () => {
      active = false
    }
  }, [workspace.configured, workspace.dataset_id])

  useEffect(() => {
    if (!workspace.configured || !workspace.dataset_id) {
      setReviewReadiness({ datasetId: null, cases: [], validation: null, error: null })
      return
    }

    let active = true
    const datasetId = workspace.dataset_id
    setReviewReadiness({ datasetId: null, cases: [], validation: null, error: null })

    Promise.all([apiClient.listCases(datasetId), apiClient.getDatabaseValidation(datasetId)])
      .then(([casesResponse, validationResponse]) => {
        if (!active) {
          return
        }
        setReviewReadiness({
          datasetId,
          cases: casesResponse,
          validation: validationResponse,
          error: null,
        })
      })
      .catch((requestError) => {
        if (!active) {
          return
        }
        setReviewReadiness({
          datasetId,
          cases: [],
          validation: null,
          error: getApiErrorMessage(requestError),
        })
      })

    return () => {
      active = false
    }
  }, [workspace.configured, workspace.dataset_id])

  async function runValidation(payload: WorkspaceSelectionValidationPayload) {
    clearValidationTimer()
    setSubmitState({ running: true, error: null })
    setValidationDialog({
      open: true,
      progress: 4,
      currentStep: VALIDATION_STEPS[0],
      result: null,
      error: null,
    })

    let stepIndex = 0
    validationTimerRef.current = window.setInterval(() => {
      stepIndex = Math.min(stepIndex + 1, VALIDATION_STEPS.length - 1)
      setValidationDialog((state) =>
        state.result || state.error
          ? state
          : {
              ...state,
              progress: Math.min(92, 6 + stepIndex * 17),
              currentStep: VALIDATION_STEPS[stepIndex],
            },
      )
    }, 420)

    try {
      const response = await apiClient.validateWorkspaceSelection(payload)
      clearValidationTimer()
      setLastValidation(response)
      if (response.workspace) {
        onWorkspaceChange(response.workspace)
        setPathInput(response.summary.dataset_root ?? response.workspace.dataset_path ?? '')
      }
      setValidationDialog({
        open: true,
        progress: 100,
        currentStep: VALIDATION_STEPS[VALIDATION_STEPS.length - 1],
        result: response,
        error: null,
      })
      setSubmitState({
        running: false,
        error:
          response.errors.length > 0
            ? 'Selection has blocking errors and was not activated.'
            : null,
      })
    } catch (requestError) {
      clearValidationTimer()
      const message = getApiErrorMessage(requestError)
      setValidationDialog({
        open: true,
        progress: 100,
        currentStep: VALIDATION_STEPS[VALIDATION_STEPS.length - 1],
        result: null,
        error: message,
      })
      setSubmitState({
        running: false,
        error: message,
      })
    }
  }

  async function submitWorkspace() {
    const trimmed = pathInput.trim()
    if (!trimmed) {
      setSubmitState({
        running: false,
        error: 'Dataset path is required.',
      })
      return
    }

    await runValidation({ dataset_folder_path: trimmed })
  }

  async function clearWorkspace() {
    setSubmitState({
      running: true,
      error: null,
    })

    try {
      const response = await apiClient.clearWorkspace()
      onWorkspaceChange(response)
      setLastValidation(null)
    } catch (requestError) {
      setSubmitState({
        running: false,
        error: getApiErrorMessage(requestError),
      })
      return
    }

    setSubmitState({
      running: false,
      error: null,
    })
  }

  function clearValidationTimer() {
    if (validationTimerRef.current !== null) {
      window.clearInterval(validationTimerRef.current)
      validationTimerRef.current = null
    }
  }

  const activeDataset = datasets[0] ?? null
  const activeReviewDatasetId = activeDataset?.dataset_id ?? workspace.dataset_id
  const readinessLoading =
    workspace.configured && reviewReadiness.datasetId !== workspace.dataset_id
  const readinessCases =
    reviewReadiness.datasetId === workspace.dataset_id ? reviewReadiness.cases : []
  const validationReport =
    reviewReadiness.datasetId === workspace.dataset_id ? reviewReadiness.validation : null
  const reviewedCases = readinessCases.filter((entry) => entry.latest_curation_status).length
  const warningCases = readinessCases.filter((entry) => entry.warning_count > 0).length
  const validationWarningCount = validationReport?.warnings.length ?? 0
  const displayedCaseCount =
    validationReport?.case_count ?? (readinessCases.length || activeDataset?.patient_count || 0)
  const activeDatabasePath =
    workspace.database_csv_path ??
    (lastValidation?.activated &&
    lastValidation.summary.dataset_root === workspace.dataset_path
      ? lastValidation.summary.database_csv_path
      : null)

  return (
    <Paper
      elevation={0}
      sx={{
        minHeight: 420,
        px: { xs: 3, md: 5 },
        py: { xs: 3, md: 4 },
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        background:
          'linear-gradient(160deg, rgba(125, 211, 252, 0.08), rgba(18, 18, 18, 0.98) 38%)',
      }}
    >
      <Stack spacing={3}>
        <Stack spacing={1.5} maxWidth={880}>
          <Typography variant="overline" color="text.secondary">
            Dataset Discovery
          </Typography>
          <Typography variant="h3">Medical curation setup</Typography>
          <Typography variant="body1" color="text.secondary">
            Select a backend-visible dataset folder or database.csv, validate it, then start review from the active workspace.
          </Typography>
        </Stack>

        {workspaceLoading ? (
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minHeight: 120 }}>
            <CircularProgress size={28} />
            <Typography color="text.secondary">Checking workspace status...</Typography>
          </Stack>
        ) : null}

        {workspaceError ? <Alert severity="error">{workspaceError}</Alert> : null}
        {submitState.error ? <Alert severity="error">{submitState.error}</Alert> : null}

        {workspace.configured ? (
          <Card
            sx={{
              borderColor: validationWarningCount > 0 ? 'warning.dark' : 'success.dark',
              background:
                'linear-gradient(150deg, rgba(125, 211, 252, 0.1), rgba(18, 18, 18, 0.98) 42%)',
            }}
          >
            <CardContent sx={{ p: { xs: 2.25, md: 3 } }}>
              <Stack spacing={2}>
                <Stack
                  direction={{ xs: 'column', md: 'row' }}
                  spacing={1.5}
                  justifyContent="space-between"
                  alignItems={{ xs: 'flex-start', md: 'center' }}
                >
                  <Box>
                    <Typography variant="overline" color="text.secondary">
                      Active Dataset
                    </Typography>
                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                      <Typography variant="h4">{workspace.dataset_id}</Typography>
                      <Chip
                        label={
                          validationReport?.has_database
                            ? 'database.csv ready'
                            : 'database.csv pending'
                        }
                        color={validationReport?.has_database ? 'success' : 'warning'}
                        variant={validationReport?.has_database ? 'filled' : 'outlined'}
                      />
                    </Stack>
                  </Box>
                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                    {activeReviewDatasetId && !settingsState.loading ? (
                      <Button
                        variant="contained"
                        onClick={() =>
                          navigate(
                            `/datasets/${activeReviewDatasetId}/review${
                              readinessCases[0]?.case_id ? `/${readinessCases[0].case_id}` : ''
                            }`,
                          )
                        }
                      >
                        Start Review
                      </Button>
                    ) : null}
                    {activeReviewDatasetId &&
                    settingsState.allSettings[activeReviewDatasetId]?.last_patient ? (
                      <Button
                        variant="outlined"
                        onClick={() =>
                          navigate(
                            `/datasets/${activeReviewDatasetId}/review/${settingsState.allSettings[activeReviewDatasetId]?.last_patient}`,
                          )
                        }
                      >
                        Resume Review
                      </Button>
                    ) : null}
                  </Stack>
                </Stack>

                {readinessLoading ? (
                  <Stack direction="row" spacing={1.5} alignItems="center">
                    <CircularProgress size={22} />
                    <Typography color="text.secondary">Loading review readiness...</Typography>
                  </Stack>
                ) : null}
                {loading ? (
                  <Stack direction="row" spacing={1.5} alignItems="center">
                    <CircularProgress size={22} />
                    <Typography color="text.secondary">Loading dataset summary...</Typography>
                  </Stack>
                ) : null}
                {!loading && error ? <Alert severity="error">{error}</Alert> : null}
                {reviewReadiness.error ? (
                  <Alert severity="warning">{reviewReadiness.error}</Alert>
                ) : null}

                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Chip label={`${displayedCaseCount} cases`} color="primary" variant="outlined" />
                  <Chip
                    label={`${reviewedCases} reviewed`}
                    color={reviewedCases > 0 ? 'success' : 'default'}
                    variant="outlined"
                  />
                  <Chip
                    label={`${warningCases} cases with warnings`}
                    color={warningCases > 0 ? 'warning' : 'default'}
                    variant={warningCases > 0 ? 'filled' : 'outlined'}
                  />
                  <Chip
                    label={`${validationWarningCount} validation warnings`}
                    color={validationWarningCount > 0 ? 'warning' : 'default'}
                    variant={validationWarningCount > 0 ? 'filled' : 'outlined'}
                  />
                  <Chip
                    label={activeDataset?.has_seg ? 'SEG available' : 'SEG missing'}
                    color={activeDataset?.has_seg ? 'success' : 'default'}
                    variant={activeDataset?.has_seg ? 'filled' : 'outlined'}
                  />
                  <Chip
                    label={activeDataset?.has_voi ? 'VOI available' : 'VOI missing'}
                    color={activeDataset?.has_voi ? 'success' : 'default'}
                    variant={activeDataset?.has_voi ? 'filled' : 'outlined'}
                  />
                </Stack>

                <Stack spacing={0.25}>
                  <Typography variant="caption" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
                    Dataset root: {workspace.dataset_path}
                  </Typography>
                  {activeDatabasePath ? (
                    <Typography variant="caption" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
                      database.csv: {activeDatabasePath}
                    </Typography>
                  ) : null}
                </Stack>
              </Stack>
            </CardContent>
          </Card>
        ) : null}

        <Card
          sx={{
            background:
              'linear-gradient(145deg, rgba(10, 10, 10, 0.78), rgba(31, 41, 55, 0.62))',
          }}
        >
          <CardContent sx={{ p: 3 }}>
            <Stack spacing={2.25}>
              <Box>
                <Typography variant="overline" color="text.secondary">
                  Dataset Selection
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Select the dataset folder on the backend server.
                </Typography>
              </Box>

              <Stack direction="row" spacing={1.5} alignItems="flex-start">
                <TextField
                  label="Dataset folder path"
                  value={pathInput}
                  onChange={(event) => setPathInput(event.target.value)}
                  placeholder="/path/to/Dataset820"
                  fullWidth
                  disabled={submitState.running || workspaceLoading}
                  helperText="Path on the backend server filesystem."
                />
                <Button
                  variant="outlined"
                  onClick={() => setBrowserOpen(true)}
                  disabled={submitState.running || workspaceLoading}
                  sx={{ mt: 1, flexShrink: 0 }}
                >
                  Browse
                </Button>
              </Stack>

              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                <Button
                  variant="contained"
                  onClick={submitWorkspace}
                  disabled={submitState.running || workspaceLoading}
                >
                  {workspace.configured ? 'Validate and Change' : 'Validate and Activate'}
                </Button>
                <Button
                  variant="outlined"
                  onClick={clearWorkspace}
                  disabled={!workspace.configured || submitState.running || workspaceLoading}
                >
                  Clear workspace
                </Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      </Stack>

      <BackendFileBrowserDialog
        open={browserOpen}
        initialPath={pathInput || '/'}
        onClose={() => setBrowserOpen(false)}
        onSelect={(selectedPath) => {
          setBrowserOpen(false)
          setPathInput(selectedPath)
          void runValidation({ dataset_folder_path: selectedPath })
        }}
      />

      <ValidationProgressDialog
        open={validationDialog.open}
        progress={validationDialog.progress}
        currentStep={validationDialog.currentStep}
        result={validationDialog.result}
        error={validationDialog.error}
        onClose={() => setValidationDialog((state) => ({ ...state, open: false }))}
      />
    </Paper>
  )
}

export default DatasetSelectorPage
