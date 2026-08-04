import { useEffect, useState, type FormEvent } from 'react'
import {
  Alert,
  Box,
  Button,
  Collapse,
  Divider,
  InputAdornment,
  LinearProgress,
  Stack,
  TextField,
  Typography,
} from '@mui/material'

import { useSettings } from '../hooks/useSettings'
import {
  apiClient,
  getApiErrorMessage,
  type DatasetKind,
  type WorkspaceInspection,
  type WorkspaceStatus,
} from '../services/api'
import {
  browseForDatasetDirectory,
  isDesktopRuntime,
} from '../services/desktop'
import { useNavigate } from '../services/router'

interface DatasetSelectorPageProps {
  workspace: WorkspaceStatus
  workspaceLoading: boolean
  workspaceError: string | null
  onWorkspaceChange: (workspace: WorkspaceStatus) => void
}

interface RequestState {
  error: string | null
  recentKey: string | null
  running: boolean
}

const EMPTY_REQUEST: RequestState = {
  error: null,
  recentKey: null,
  running: false,
}

function DatasetSelectorPage({
  workspace,
  workspaceLoading,
  workspaceError,
  onWorkspaceChange,
}: DatasetSelectorPageProps) {
  const navigate = useNavigate()
  const settingsState = useSettings({ enabled: workspace.configured })
  const [pathInput, setPathInput] = useState(workspace.dataset_path ?? '')
  const [inspection, setInspection] = useState<WorkspaceInspection | null>(null)
  const [requestState, setRequestState] = useState<RequestState>(EMPTY_REQUEST)
  const hasDesktopBridge = isDesktopRuntime()

  useEffect(() => {
    setPathInput(workspace.dataset_path ?? '')
  }, [workspace.dataset_path])

  const savedCaseId = workspace.dataset_id
    ? settingsState.allSettings[workspace.dataset_id]?.last_patient
    : null
  const isBusy = workspaceLoading || requestState.running

  function changePath(nextPath: string) {
    setPathInput(nextPath)
    setInspection(null)
    setRequestState(EMPTY_REQUEST)
  }

  async function inspectCandidate(
    candidatePath: string,
    options: { openImmediately?: boolean; resumeId?: string | null; recentKey?: string } = {},
  ) {
    const trimmed = candidatePath.trim()
    if (!trimmed) {
      setRequestState({ error: 'Dataset path is required.', recentKey: null, running: false })
      return
    }

    setPathInput(trimmed)
    setInspection(null)
    setRequestState({ error: null, recentKey: options.recentKey ?? null, running: true })

    try {
      const result = await apiClient.inspectWorkspace(trimmed)
      setInspection(result)
      setPathInput(result.dataset_path)
      if (options.openImmediately && result.valid) {
        await activateDataset(result, options.resumeId ?? null)
        return
      }
      setRequestState({ error: null, recentKey: options.recentKey ?? null, running: false })
    } catch (error) {
      setRequestState({
        error: getApiErrorMessage(error),
        recentKey: options.recentKey ?? null,
        running: false,
      })
    }
  }

  async function activateDataset(
    result: WorkspaceInspection,
    resumeId: string | null = null,
  ): Promise<boolean> {
    setRequestState((current) => ({ ...current, error: null, running: true }))
    try {
      const nextWorkspace = await apiClient.putWorkspace(result.dataset_path)
      if (!nextWorkspace.dataset_id || !nextWorkspace.dataset_kind) {
        throw new Error('The activated workspace response is incomplete.')
      }
      onWorkspaceChange(nextWorkspace)
      navigate(
        destinationFor(
          nextWorkspace.dataset_kind,
          nextWorkspace.dataset_id,
          nextWorkspace.dataset_key === result.dataset_key ? resumeId : null,
        ),
      )
      return true
    } catch (error) {
      setRequestState((current) => ({
        ...current,
        error: getApiErrorMessage(error),
        running: false,
      }))
      return false
    }
  }

  async function submitInspection(event: FormEvent) {
    event.preventDefault()
    await inspectCandidate(pathInput)
  }

  async function browseForDataset() {
    try {
      const selectedPath = await browseForDatasetDirectory()
      if (selectedPath) {
        changePath(selectedPath)
      }
    } catch (error) {
      setRequestState({ error: getApiErrorMessage(error), recentKey: null, running: false })
    }
  }

  async function removeUnavailableRecent() {
    const key = requestState.recentKey
    if (!key) {
      return
    }
    setRequestState((current) => ({ ...current, running: true }))
    try {
      const nextWorkspace = await apiClient.clearWorkspace(key)
      onWorkspaceChange(nextWorkspace)
      setInspection(null)
      setRequestState(EMPTY_REQUEST)
    } catch (error) {
      setRequestState((current) => ({
        ...current,
        error: getApiErrorMessage(error),
        running: false,
      }))
    }
  }

  return (
    <Box
      component="main"
      sx={{
        minHeight: '100vh',
        backgroundColor: '#0f1213',
        color: 'text.primary',
      }}
    >
      <Box
        sx={{
          width: 'min(920px, 100%)',
          mx: 'auto',
          px: { xs: 2.5, sm: 4, md: 6 },
          py: { xs: 4, sm: 6, md: 8 },
        }}
      >
        <Stack spacing={{ xs: 4, md: 5 }}>
          <Box>
            <Typography
              variant="overline"
              sx={{ color: '#93a4aa', letterSpacing: '0.22em' }}
            >
              Radiology
            </Typography>
            <Typography
              component="h1"
              sx={{
                mt: 1.25,
                fontFamily: '"IBM Plex Serif", Georgia, serif',
                fontSize: { xs: '2.4rem', md: '3.35rem' },
                fontWeight: 500,
                lineHeight: 1.04,
                letterSpacing: '-0.035em',
              }}
            >
              Open Dataset
            </Typography>
            <Typography color="text.secondary" sx={{ mt: 1.5, maxWidth: 620 }}>
              Select a dataset containing NIfTI volumes and metadata. Inspection is read-only
              until you choose to open it.
            </Typography>
          </Box>

          {workspace.configured && workspace.dataset_path && workspace.dataset_id ? (
            <CurrentDataset
              datasetId={workspace.dataset_id}
              datasetKind={workspace.dataset_kind}
              datasetPath={workspace.dataset_path}
              disabled={isBusy}
              resumeId={savedCaseId}
              onOpen={() =>
                void inspectCandidate(workspace.dataset_path ?? '', { openImmediately: true })
              }
              onResume={() =>
                void inspectCandidate(workspace.dataset_path ?? '', {
                  openImmediately: true,
                  resumeId: savedCaseId,
                })
              }
            />
          ) : null}

          <Box component="form" onSubmit={(event) => void submitInspection(event)}>
            <Stack spacing={1.5}>
              <TextField
                label="Dataset path visible to the server"
                value={pathInput}
                onChange={(event) => changePath(event.target.value)}
                placeholder={hasDesktopBridge ? 'C:\\Research\\Dataset420' : '/data/Dataset420'}
                fullWidth
                disabled={isBusy}
                inputProps={{ maxLength: 4096 }}
                InputProps={{
                  endAdornment: hasDesktopBridge ? (
                    <InputAdornment position="end">
                      <Button
                        type="button"
                        variant="text"
                        disabled={isBusy}
                        onClick={() => void browseForDataset()}
                        sx={{ borderRadius: 1, px: 1.5 }}
                      >
                        Browse…
                      </Button>
                    </InputAdornment>
                  ) : undefined,
                }}
                sx={{
                  '& .MuiOutlinedInput-root': {
                    borderRadius: 1,
                    backgroundColor: '#15191a',
                  },
                }}
              />
              <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                <Button
                  type="submit"
                  variant="outlined"
                  disabled={isBusy || !pathInput.trim()}
                  sx={{ borderRadius: 1, minWidth: 118 }}
                >
                  Inspect
                </Button>
              </Box>
              <Box sx={{ height: 2 }}>
                <LinearProgress
                  aria-label="Dataset operation in progress"
                  sx={{ visibility: isBusy ? 'visible' : 'hidden' }}
                />
              </Box>
            </Stack>
          </Box>

          <Box aria-live="polite" sx={{ minHeight: 56 }}>
            {workspaceError ? <Alert severity="error">{workspaceError}</Alert> : null}
            {settingsState.loadError ? (
              <Alert severity="warning">{settingsState.loadError}</Alert>
            ) : null}
            {requestState.error ? (
              <Stack spacing={1}>
                <Alert severity="error">{requestState.error}</Alert>
                {requestState.recentKey ? (
                  <Box>
                    <Button
                      variant="text"
                      color="secondary"
                      disabled={requestState.running}
                      onClick={() => void removeUnavailableRecent()}
                    >
                      Remove from recent
                    </Button>
                  </Box>
                ) : null}
              </Stack>
            ) : null}
          </Box>

          <Box sx={{ minHeight: { xs: 260, md: 330 } }}>
            {inspection ? (
              <InspectionResult
                inspection={inspection}
                disabled={requestState.running}
                onOpen={() => void activateDataset(inspection)}
              />
            ) : (
              <Box sx={{ borderTop: '1px solid', borderColor: 'divider', pt: 2 }}>
                <Typography variant="body2" color="text.secondary">
                  Dataset details will appear here after inspection.
                </Typography>
              </Box>
            )}
          </Box>

          {workspace.recent_datasets.length > 0 ? (
            <Box component="section" aria-labelledby="recent-datasets-title">
              <Typography id="recent-datasets-title" variant="h6" sx={{ mb: 1 }}>
                Recent datasets
              </Typography>
              <Stack divider={<Divider flexItem />} sx={{ borderBlock: '1px solid', borderColor: 'divider' }}>
                {workspace.recent_datasets.map((recent) => (
                  <Button
                    key={recent.dataset_key}
                    variant="text"
                    disabled={isBusy}
                    onClick={() =>
                      void inspectCandidate(recent.dataset_path, { recentKey: recent.dataset_key })
                    }
                    sx={{
                      borderRadius: 0,
                      justifyContent: 'space-between',
                      py: 1.5,
                      px: 0,
                      textAlign: 'left',
                      textTransform: 'none',
                      color: 'text.primary',
                    }}
                  >
                    <Box sx={{ minWidth: 0 }}>
                      <Typography fontWeight={650}>{recent.display_name}</Typography>
                      <Typography
                        variant="body2"
                        color="text.secondary"
                        sx={{ overflowWrap: 'anywhere', textTransform: 'none' }}
                      >
                        {recent.dataset_path}
                      </Typography>
                    </Box>
                    <Box sx={{ pl: 2, flexShrink: 0, textAlign: 'right' }}>
                      <Typography variant="caption" display="block" color="text.secondary">
                        {formatKind(recent.dataset_kind)}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {formatDate(recent.last_opened_at)}
                      </Typography>
                    </Box>
                  </Button>
                ))}
              </Stack>
            </Box>
          ) : null}
        </Stack>
      </Box>
    </Box>
  )
}

function CurrentDataset({
  datasetId,
  datasetKind,
  datasetPath,
  disabled,
  resumeId,
  onOpen,
  onResume,
}: {
  datasetId: string
  datasetKind: DatasetKind | null
  datasetPath: string
  disabled: boolean
  resumeId: string | null
  onOpen: () => void
  onResume: () => void
}) {
  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      justifyContent="space-between"
      alignItems={{ sm: 'center' }}
      spacing={1.5}
      sx={{ borderBlock: '1px solid', borderColor: 'divider', py: 1.75 }}
    >
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="caption" color="text.secondary">
          Current dataset · {formatKind(datasetKind)}
        </Typography>
        <Typography fontWeight={650}>{datasetId}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>
          {datasetPath}
        </Typography>
      </Box>
      <Stack direction="row" spacing={0.5} flexShrink={0}>
        <Button variant="text" disabled={disabled} onClick={onOpen}>
          Open last dataset
        </Button>
        {resumeId ? (
          <Button variant="text" disabled={disabled} onClick={onResume}>
            Resume {resumeId}
          </Button>
        ) : null}
      </Stack>
    </Stack>
  )
}

function InspectionResult({
  disabled,
  inspection,
  onOpen,
}: {
  disabled: boolean
  inspection: WorkspaceInspection
  onOpen: () => void
}) {
  const [detailsOpen, setDetailsOpen] = useState(false)
  const hasMetadata =
    inspection.markers.database_csv ||
    inspection.markers.metadata_jsonl ||
    inspection.markers.manifest_csv
  const rows = [
    ['Cases', inspection.summary.case_count.toLocaleString()],
    ['NIfTI volumes', inspection.summary.nifti_count.toLocaleString()],
    ['Segmentation masks', inspection.summary.segmentation_count.toLocaleString()],
    ['Metadata', hasMetadata ? 'Available' : 'Not found'],
    ['State directory', inspection.state.writable ? 'Writable' : 'Read only'],
  ] as const

  return (
    <Stack spacing={2.5} sx={{ borderTop: '1px solid', borderColor: 'divider', pt: 2.5 }}>
      <Box>
        <Typography
          variant="caption"
          color={inspection.valid ? 'primary.main' : 'secondary.main'}
          fontWeight={700}
        >
          {inspection.valid ? 'Ready to open' : 'Activation blocked'}
        </Typography>
        <Typography variant="h4" sx={{ mt: 0.5 }}>
          {inspection.dataset_id}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {formatKind(inspection.dataset_kind)}
        </Typography>
      </Box>

      <Stack divider={<Divider flexItem />} sx={{ borderBlock: '1px solid', borderColor: 'divider' }}>
        {rows.map(([label, value]) => (
          <Stack
            key={label}
            direction="row"
            justifyContent="space-between"
            spacing={2}
            sx={{ py: 1.15 }}
          >
            <Typography variant="body2" color="text.secondary">
              {label}
            </Typography>
            <Typography variant="body2" fontWeight={650} sx={{ textAlign: 'right' }}>
              {value}
            </Typography>
          </Stack>
        ))}
      </Stack>

      {inspection.summary.warning_count > 0 ? (
        <Box>
          <Stack direction="row" alignItems="center" spacing={1}>
            <Typography variant="body2" color="secondary.main" fontWeight={650}>
              {inspection.summary.warning_count} warning
              {inspection.summary.warning_count === 1 ? '' : 's'}
            </Typography>
            <Button
              variant="text"
              size="small"
              aria-expanded={detailsOpen}
              onClick={() => setDetailsOpen((open) => !open)}
            >
              {detailsOpen ? 'Hide details' : 'Details'}
            </Button>
          </Stack>
          <Collapse in={detailsOpen}>
            <Stack spacing={1} sx={{ mt: 1.5 }}>
              {inspection.warnings.map((warning, index) => (
                <Box
                  key={`${warning.code}-${index}`}
                  sx={{ borderLeft: '2px solid', borderColor: 'divider', pl: 1.5 }}
                >
                  <Typography variant="body2">{warning.message}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {warning.code}
                  </Typography>
                </Box>
              ))}
              {inspection.summary.warnings_truncated ? (
                <Typography variant="caption" color="text.secondary">
                  Additional warning details were omitted from this preview.
                </Typography>
              ) : null}
            </Stack>
          </Collapse>
        </Box>
      ) : null}

      {inspection.valid ? (
        <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Button
            variant="contained"
            disabled={disabled}
            onClick={onOpen}
            sx={{ borderRadius: 1, minWidth: 150 }}
          >
            Open dataset
          </Button>
        </Box>
      ) : (
        <Alert severity="warning">
          This dataset remains available for diagnosis only. The active workspace was not changed.
        </Alert>
      )}
    </Stack>
  )
}

function destinationFor(kind: DatasetKind, datasetId: string, resumeId: string | null) {
  const encodedDatasetId = encodeURIComponent(datasetId)
  if (kind === 'canonical' || kind === 'converter_output') {
    return resumeId
      ? `/datasets/${encodedDatasetId}/cases/${encodeURIComponent(resumeId)}/review`
      : `/datasets/${encodedDatasetId}/cases`
  }
  return resumeId
    ? `/datasets/${encodedDatasetId}/patients/${encodeURIComponent(resumeId)}/viewer`
    : `/datasets/${encodedDatasetId}/patients`
}

function formatKind(kind: DatasetKind | null) {
  if (!kind) {
    return 'Requires inspection'
  }
  const labels: Record<DatasetKind, string> = {
    canonical: 'Canonical dataset',
    converter_output: 'Converter output',
    legacy: 'Legacy dataset',
    nifti_collection: 'NIfTI collection',
    voi_collection: 'VOI collection',
    incomplete: 'Incomplete dataset',
    unsupported: 'Unsupported path',
  }
  return labels[kind]
}

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Unknown date' : date.toLocaleDateString()
}

export default DatasetSelectorPage
