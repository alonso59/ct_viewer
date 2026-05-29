import {
  Alert,
  Button,
  Chip,
  Divider,
  FormControl,
  InputLabel,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useEffect, useState, type ReactNode } from 'react'

import {
  apiClient,
  getApiErrorMessage,
  type CaseInventoryRow,
  type CurationDecision,
  type CurationPriority,
  type CurationStatus,
  type CurationTarget,
  type Scope,
} from '../../services/api'
import {
  formatDate,
  formatStatus,
  quickStatusForButton,
  statusChipColor,
} from './reviewUi'

interface DecisionPanelProps {
  caseId: string
  datasetId: string
  latestDecision: CurationDecision | null
  onError: (message: string) => void
  onSaved: (decision: CurationDecision, queued: boolean) => void
  queueButton: ReactNode
  row: CaseInventoryRow | null
  scope: Scope
  selectedSourceQueued: boolean
  sourceLabel: string
  viewerControls: ReactNode
}

const QUICK_STATUSES: CurationStatus[] = [
  'accepted',
  'needs_major_correction',
  'rejected',
  'cannot_assess',
]

function DecisionPanel({
  caseId,
  datasetId,
  latestDecision,
  onError,
  onSaved,
  queueButton,
  row,
  scope,
  selectedSourceQueued,
  sourceLabel,
  viewerControls,
}: DecisionPanelProps) {
  const [target, setTarget] = useState<CurationTarget>('SEG')
  const [status, setStatus] = useState<CurationStatus>('not_reviewed')
  const [priority, setPriority] = useState<CurationPriority>('medium')
  const [comment, setComment] = useState('')
  const [proposedPhase, setProposedPhase] = useState('')
  const [reviewer, setReviewer] = useState('')
  const [saving, setSaving] = useState(false)
  const [savedNotice, setSavedNotice] = useState<string | null>(null)
  const showProposedPhase = target === 'phase_issue' || status === 'wrong_phase_suspected'

  useEffect(() => {
    setSavedNotice(null)
  }, [row?.row_id, scope])

  async function saveDecision(addToQueue: boolean) {
    if (!row || saving) {
      return
    }
    setSaving(true)
    try {
      const decision = await apiClient.saveCurationDecision(datasetId, {
        case_id: caseId,
        row_id: row.row_id,
        scope,
        target,
        status,
        priority,
        comment,
        proposed_phase: showProposedPhase ? proposedPhase : null,
        reviewer,
        add_to_queue: addToQueue,
      })
      setSavedNotice(addToQueue ? 'Saved and added to correction queue.' : 'QC decision saved.')
      onSaved(decision, addToQueue)
    } catch (error) {
      onError(getApiErrorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Paper
      elevation={0}
      data-testid="decision-panel"
      sx={{
        height: { lg: '100%' },
        minHeight: 0,
        p: 1.5,
        borderColor: status !== 'not_reviewed' ? `${statusChipColor(status)}.main` : 'divider',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <Stack spacing={1.25} sx={{ flex: 1, minHeight: 0 }}>
        <Stack spacing={0.55}>
          <Typography variant="overline" color="text.secondary">
            Segmentation QC
          </Typography>
          <Typography variant="h6" sx={{ lineHeight: 1.15 }}>
            Decision for selected source
          </Typography>
          <Stack direction="row" spacing={0.65} flexWrap="wrap" useFlexGap>
            <Chip label={sourceLabel} size="small" color="primary" variant="outlined" />
            <Chip
              label={`Latest ${formatStatus(row?.latest_curation_status)}`}
              color={statusChipColor(row?.latest_curation_status)}
              size="small"
              variant={row?.latest_curation_status ? 'filled' : 'outlined'}
            />
            <Chip
              label={selectedSourceQueued ? 'Queued' : 'Not queued'}
              color={selectedSourceQueued ? 'warning' : 'default'}
              size="small"
              variant={selectedSourceQueued ? 'filled' : 'outlined'}
            />
          </Stack>
        </Stack>

        {latestDecision ? (
          <Alert severity="info" variant="outlined">
            Latest: {formatStatus(latestDecision.status)} by{' '}
            {latestDecision.reviewer || 'unknown reviewer'} on {formatDate(latestDecision.reviewed_at)}
          </Alert>
        ) : null}
        {savedNotice ? <Alert severity="success">{savedNotice}</Alert> : null}

        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
          {QUICK_STATUSES.map((quickStatus) => (
            <Button
              key={quickStatus}
              size="small"
              variant={status === quickStatus ? 'contained' : 'outlined'}
              color={quickStatus === 'rejected' && status === quickStatus ? 'error' : 'primary'}
              onClick={() => setStatus(quickStatus)}
            >
              {quickStatusForButton(quickStatus)}
            </Button>
          ))}
        </Stack>

        <Divider />

        <Stack
          spacing={1.1}
          sx={{ flex: 1, minHeight: 0, overflow: { lg: 'auto' }, pr: { lg: 0.35 } }}
        >
          <FormControl fullWidth size="small">
            <InputLabel id="curation-target-label" htmlFor="curation-target">
              Target
            </InputLabel>
            <Select
              labelId="curation-target-label"
              label="Target"
              native
              inputProps={{ id: 'curation-target' }}
              value={target}
              onChange={(event) => setTarget(event.target.value as CurationTarget)}
            >
              <option value="SEG">SEG</option>
              <option value="tumor_mask">Tumor mask</option>
              <option value="kidney_mask">Kidney mask</option>
              <option value="cyst_mask">Cyst mask</option>
              <option value="VOI_mask">VOI mask</option>
              <option value="phase_issue">Phase issue flag</option>
              <option value="side_laterality_issue">Side/laterality issue flag</option>
            </Select>
          </FormControl>
          <FormControl fullWidth size="small">
            <InputLabel id="curation-status-label" htmlFor="curation-status">
              Status
            </InputLabel>
            <Select
              labelId="curation-status-label"
              label="Status"
              native
              inputProps={{ id: 'curation-status' }}
              value={status}
              onChange={(event) => setStatus(event.target.value as CurationStatus)}
            >
              <option value="not_reviewed">Not reviewed</option>
              <option value="accepted">Accepted</option>
              <option value="needs_minor_correction">Needs minor correction</option>
              <option value="needs_major_correction">Needs major correction</option>
              <option value="rejected">Rejected</option>
              <option value="missing">Missing</option>
              <option value="wrong_phase_suspected">Wrong phase suspected</option>
              <option value="wrong_side_suspected">Wrong side suspected</option>
              <option value="cannot_assess">Cannot assess</option>
            </Select>
          </FormControl>
          <FormControl fullWidth size="small">
            <InputLabel id="curation-priority-label" htmlFor="curation-priority">
              Priority
            </InputLabel>
            <Select
              labelId="curation-priority-label"
              label="Priority"
              native
              inputProps={{ id: 'curation-priority' }}
              value={priority}
              onChange={(event) => setPriority(event.target.value as CurationPriority)}
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </Select>
          </FormControl>
          {showProposedPhase ? (
            <Stack spacing={1}>
              <Alert severity="warning">
                This records a phase correction proposal only. Source images and database.csv are
                not modified by this review action.
              </Alert>
              <TextField
                label="Proposed phase"
                size="small"
                value={proposedPhase}
                onChange={(event) => setProposedPhase(event.target.value)}
              />
            </Stack>
          ) : null}
          <TextField
            label="Reviewer"
            size="small"
            value={reviewer}
            onChange={(event) => setReviewer(event.target.value)}
          />
          <TextField
            label="Comment"
            multiline
            minRows={2}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
          />
          <Stack direction={{ xs: 'column', sm: 'row', lg: 'column', xl: 'row' }} spacing={1}>
            <Button
              data-testid="save-qc-decision"
              disabled={!row || saving}
              variant="contained"
              fullWidth
              onClick={() => void saveDecision(false)}
            >
              {saving ? 'Saving...' : 'Save QC decision'}
            </Button>
            <Button
              disabled={!row || saving}
              variant="outlined"
              fullWidth
              onClick={() => void saveDecision(true)}
            >
              Add to correction queue
            </Button>
          </Stack>
          {queueButton}
          {viewerControls}
        </Stack>
      </Stack>
    </Paper>
  )
}

export default DecisionPanel
