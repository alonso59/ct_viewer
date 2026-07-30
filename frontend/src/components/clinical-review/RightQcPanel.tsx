import {
  Alert,
  Button,
  Chip,
  Divider,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'

import {
  apiClient,
  getApiErrorMessage,
  type CaseInventoryRow,
  type CurationDecision,
  type CurationStatus,
  type Scope,
} from '../../services/api'
import { formatDate, formatStatus } from './reviewUi'

interface RightQcPanelProps {
  caseId: string
  caseQueued: boolean
  datasetId: string
  latestDecision: CurationDecision | null
  missingSegBlocked: boolean
  noSource: boolean
  onError: (message: string) => void
  onSaved: (decision: CurationDecision, queued: boolean, advance: boolean) => void
  row: CaseInventoryRow | null
  scope: Scope
  sourceLabel: string
}

const QC_STATUSES: Array<{ label: string; value: CurationStatus }> = [
  { label: 'Accept', value: 'accepted' },
  { label: 'Needs correction', value: 'needs_major_correction' },
  { label: 'Reject', value: 'rejected' },
  { label: 'Cannot assess', value: 'cannot_assess' },
]

function RightQcPanel({
  caseId,
  caseQueued,
  datasetId,
  latestDecision,
  missingSegBlocked,
  noSource,
  onError,
  onSaved,
  row,
  scope,
  sourceLabel,
}: RightQcPanelProps) {
  const [status, setStatus] = useState<CurationStatus>('accepted')
  const [comment, setComment] = useState('')
  const [reviewer, setReviewer] = useState('')
  const [saving, setSaving] = useState(false)
  const [savedNotice, setSavedNotice] = useState<string | null>(null)

  useEffect(() => {
    setSavedNotice(null)
  }, [caseId, row?.row_id, scope])

  const blockedReason = noSource
    ? 'Load a source before saving QC.'
    : missingSegBlocked
      ? 'Missing SEG blocks case QC.'
      : null
  const needsCorrection = status === 'needs_major_correction'

  async function saveDecision(advance: boolean) {
    if (!row || saving || blockedReason) {
      return
    }
    setSaving(true)
    try {
      const decision = await apiClient.saveCurationDecision(datasetId, {
        case_id: caseId,
        row_id: row.row_id,
        scope,
        target: 'SEG',
        status,
        priority: needsCorrection ? 'high' : 'medium',
        comment,
        reviewer,
        add_to_queue: needsCorrection,
      })
      setSavedNotice(needsCorrection ? 'Saved and queued for correction.' : 'QC decision saved.')
      onSaved(decision, needsCorrection, advance)
    } catch (error) {
      onError(getApiErrorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Stack data-testid="right-qc-panel" spacing={1.05}>
      <Stack spacing={0.45}>
        <Chip label={sourceLabel} size="small" color="primary" variant="outlined" />
        <Chip
          label={caseQueued ? 'Queued' : 'Not queued'}
          size="small"
          color={caseQueued ? 'warning' : 'default'}
          variant={caseQueued ? 'filled' : 'outlined'}
        />
      </Stack>

      {latestDecision ? (
        <Alert severity="info" variant="outlined" sx={{ py: 0.4 }}>
          Latest {formatStatus(latestDecision.status)} by {latestDecision.reviewer || 'unknown'} on{' '}
          {formatDate(latestDecision.reviewed_at)}
        </Alert>
      ) : null}
      {blockedReason ? <Alert severity="error">{blockedReason}</Alert> : null}
      {savedNotice ? <Alert severity="success">{savedNotice}</Alert> : null}

      <ToggleButtonGroup
        exclusive
        orientation="vertical"
        size="small"
        value={status}
        onChange={(_, value: CurationStatus | null) => {
          if (value) {
            setStatus(value)
          }
        }}
        data-testid="case-qc-actions"
      >
        {QC_STATUSES.map((entry) => (
          <ToggleButton key={entry.value} value={entry.value}>
            {entry.label}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>

      <TextField
        label="Reviewer"
        size="small"
        value={reviewer}
        onChange={(event) => setReviewer(event.target.value)}
      />
      <TextField
        label="Comment optional"
        size="small"
        multiline
        minRows={3}
        value={comment}
        onChange={(event) => setComment(event.target.value)}
      />

      <Divider />

      <Stack spacing={0.75}>
        {needsCorrection ? (
          <Typography variant="caption" color="warning.main">
            Needs correction automatically queues this case.
          </Typography>
        ) : null}
        <Button
          data-testid="save-and-next"
          disabled={saving || Boolean(blockedReason)}
          variant="contained"
          fullWidth
          onClick={() => void saveDecision(true)}
        >
          {saving ? 'Saving...' : 'Save & Next'}
        </Button>
        <Button
          data-testid="save-qc-only"
          disabled={saving || Boolean(blockedReason)}
          variant="outlined"
          fullWidth
          onClick={() => void saveDecision(false)}
        >
          Save only
        </Button>
      </Stack>
    </Stack>
  )
}

export default RightQcPanel
