import { useEffect, useState } from 'react'
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
import { useNavigate } from '../services/router'

import { useSettings } from '../hooks/useSettings'
import {
  apiClient,
  type DatasetSummary,
  type WorkspaceStatus,
  getApiErrorMessage,
} from '../services/api'

interface DatasetSelectorPageProps {
  workspace: WorkspaceStatus
  workspaceLoading: boolean
  workspaceError: string | null
  onWorkspaceChange: (workspace: WorkspaceStatus) => void
}

function DatasetSelectorPage({
  workspace,
  workspaceLoading,
  workspaceError,
  onWorkspaceChange,
}: DatasetSelectorPageProps) {
  const navigate = useNavigate()
  const settingsState = useSettings({ enabled: workspace.configured })
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

  useEffect(() => {
    setPathInput(workspace.dataset_path ?? '')
  }, [workspace.dataset_path])

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

  async function submitWorkspace() {
    const trimmed = pathInput.trim()
    if (!trimmed) {
      setSubmitState({
        running: false,
        error: 'Dataset path is required.',
      })
      return
    }

    setSubmitState({
      running: true,
      error: null,
    })

    try {
      const response = await apiClient.putWorkspace(trimmed)
      onWorkspaceChange(response)
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

  async function clearWorkspace() {
    setSubmitState({
      running: true,
      error: null,
    })

    try {
      const response = await apiClient.clearWorkspace()
      onWorkspaceChange(response)
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

  const activeDataset = datasets[0] ?? null

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
        <Stack spacing={1.5} maxWidth={820}>
          <Typography variant="overline" color="text.secondary">
            Workspace Setup
          </Typography>
          <Typography variant="h3">Dataset Workspace</Typography>
          <Typography variant="body1" color="text.secondary">
            Enter the server path to one dataset folder. The app will validate the
            folder, create <code>.webui/</code> inside it, and use that folder as the
            active workspace.
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

        <Card
          sx={{
            background:
              'linear-gradient(145deg, rgba(10, 10, 10, 0.9), rgba(31, 41, 55, 0.9))',
          }}
        >
          <CardContent sx={{ p: 3 }}>
            <Stack spacing={2}>
              <TextField
                label="Dataset folder path on server"
                value={pathInput}
                onChange={(event) => setPathInput(event.target.value)}
                placeholder="/path/to/Dataset820"
                fullWidth
                disabled={submitState.running || workspaceLoading}
              />

              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                <Button
                  variant="contained"
                  onClick={submitWorkspace}
                  disabled={submitState.running || workspaceLoading}
                >
                  {workspace.configured ? 'Change dataset folder' : 'Activate dataset folder'}
                </Button>
                <Button
                  variant="outlined"
                  onClick={clearWorkspace}
                  disabled={!workspace.configured || submitState.running || workspaceLoading}
                >
                  Clear workspace
                </Button>
              </Stack>

              <Typography variant="body2" color="text.secondary">
                The path must exist on the backend server filesystem and contain at
                least one of <code>database.csv</code>, <code>nifti/</code>, <code>seg/</code>, <code>voi/</code>, or
                <code> manifest.csv</code>, or <code> metadata.jsonl</code>.
              </Typography>
            </Stack>
          </CardContent>
        </Card>

        {workspace.configured ? (
          <Card
            sx={{
              background:
                'linear-gradient(150deg, rgba(125, 211, 252, 0.08), rgba(18, 18, 18, 0.98) 42%)',
            }}
          >
            <CardContent sx={{ p: 3 }}>
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
                      <Chip label="Workspace active" color="primary" variant="outlined" />
                    </Stack>
                  </Box>
                  {activeDataset && !settingsState.loading ? (
                    <Button
                      variant="outlined"
                      onClick={() =>
                        navigate(`/datasets/${activeDataset.dataset_id}/cases`)
                      }
                    >
                      Open cases
                    </Button>
                  ) : null}
                </Stack>

                <Typography variant="body2" color="text.secondary">
                  Dataset path: {workspace.dataset_path}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Workspace directory: {workspace.workspace_dir}
                </Typography>

                {loading ? (
                  <Stack direction="row" spacing={1.5} alignItems="center">
                    <CircularProgress size={24} />
                    <Typography color="text.secondary">Loading dataset summary...</Typography>
                  </Stack>
                ) : null}

                {!loading && error ? <Alert severity="error">{error}</Alert> : null}

                {!loading && !error && activeDataset ? (
                  <Stack spacing={1.5}>
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                      <Chip
                        label={`${activeDataset.patient_count} patients`}
                        color="primary"
                        variant="outlined"
                      />
                      <Chip
                        label={activeDataset.has_nifti ? 'NIfTI' : 'No NIfTI'}
                        color={activeDataset.has_nifti ? 'primary' : 'default'}
                        variant={activeDataset.has_nifti ? 'filled' : 'outlined'}
                      />
                      <Chip
                        label={activeDataset.has_seg ? 'SEG' : 'No SEG'}
                        color={activeDataset.has_seg ? 'secondary' : 'default'}
                        variant={activeDataset.has_seg ? 'filled' : 'outlined'}
                      />
                      <Chip
                        label={activeDataset.has_voi ? 'VOI' : 'No VOI'}
                        color={activeDataset.has_voi ? 'success' : 'default'}
                        variant={activeDataset.has_voi ? 'filled' : 'outlined'}
                      />
                      <Chip
                        label={activeDataset.has_metadata ? 'metadata.jsonl' : 'No metadata.jsonl'}
                        color={activeDataset.has_metadata ? 'success' : 'default'}
                        variant={activeDataset.has_metadata ? 'filled' : 'outlined'}
                      />
                    </Stack>
                    {settingsState.allSettings[activeDataset.dataset_id]?.last_patient ? (
                      <Button
                        size="small"
                        variant="text"
                        onClick={() =>
                          navigate(
                            `/datasets/${activeDataset.dataset_id}/cases/${settingsState.allSettings[activeDataset.dataset_id]?.last_patient}/review`,
                          )
                        }
                      >
                        Resume {settingsState.allSettings[activeDataset.dataset_id]?.last_patient}
                      </Button>
                    ) : null}
                  </Stack>
                ) : null}
              </Stack>
            </CardContent>
          </Card>
        ) : null}
      </Stack>
    </Paper>
  )
}

export default DatasetSelectorPage
