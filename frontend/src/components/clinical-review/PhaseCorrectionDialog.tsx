import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import React, { useEffect, useMemo, useState } from 'react'

import {
  apiClient,
  getApiErrorMessage,
  type CaseInventoryRow,
  type CurationDecision,
} from '../../services/api'

interface PhaseCorrectionDialogProps {
  open: boolean
  caseId: string
  datasetId: string
  rows: CaseInventoryRow[]
  /** Pre-selected scan_idx (null = default/no scan). Passed from the row the user clicked. */
  initialScanIdx: string | null
  onClose: () => void
  onSaved: (decision: CurationDecision) => void
}

function PhaseCorrectionDialog({
  open,
  caseId,
  datasetId,
  rows,
  initialScanIdx,
  onClose,
  onSaved,
}: PhaseCorrectionDialogProps) {
  const [proposedPhase, setProposedPhase] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // Reset state when dialog opens or scan changes
  useEffect(() => {
    if (open) {
      setProposedPhase('')
      setError(null)
      setSuccess(null)
      setSaving(false)
    }
  }, [open, initialScanIdx])

  // Rows that belong to this scan_idx (both complete and VOI scopes)
  const affectedRows = useMemo(
    () => rows.filter((r) => (r.scan_idx ?? null) === initialScanIdx),
    [rows, initialScanIdx],
  )

  const currentPhase = affectedRows[0]?.canonical_phase ?? '-'

  function handleClose() {
    if (!saving) {
      onClose()
    }
  }

  async function handleConfirm() {
    if (!proposedPhase.trim()) {
      setError('Proposed phase is required.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const result = await apiClient.savePhaseCorrectionByScan(datasetId, {
        case_id: caseId,
        scan_idx: initialScanIdx,
        proposed_phase: proposedPhase.trim(),
        add_to_queue: true,
      })
      const plural = result.total_rows !== 1 ? 's' : ''
      setSuccess(
        `Recorded for ${result.total_rows} source${plural} ` +
          `(${result.complete_rows} complete, ${result.voi_rows} VOI).`,
      )
      if (result.decisions.length > 0) {
        onSaved(result.decisions[0])
      }
    } catch (err) {
      setError(getApiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} fullWidth maxWidth="xs">
      <DialogTitle>Phase correction — scan {initialScanIdx ?? '–'}</DialogTitle>
      <DialogContent>
        <Stack spacing={1.5} sx={{ pt: 0.5 }}>
          <Typography variant="body2" color="text.secondary">
            Records a phase-correction proposal in the correction queue. No files are moved and
            database.csv is not modified.
          </Typography>

          {/* Affected sources */}
          {affectedRows.length > 0 ? (
            <Stack spacing={0.5}>
              <Typography variant="caption" color="text.secondary">
                Will be recorded for:
              </Typography>
              <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                {affectedRows.flatMap((row) => {
                  const chips: React.ReactNode[] = []
                  if (row.scope_availability.complete) {
                    chips.push(
                      <Chip
                        key={`${row.row_id}-complete`}
                        size="small"
                        label={`Complete`}
                        variant="outlined"
                      />,
                    )
                  }
                  if (row.scope_availability.voi) {
                    chips.push(
                      <Chip
                        key={`${row.row_id}-voi`}
                        size="small"
                        color="success"
                        label={`VOI${row.side ? ` ${row.side}` : ''}`}
                        variant="outlined"
                      />,
                    )
                  }
                  return chips
                })}
              </Stack>
            </Stack>
          ) : null}

          <TextField
            label="Current phase"
            size="small"
            value={currentPhase}
            InputProps={{ readOnly: true }}
          />
          <TextField
            label="Proposed phase"
            size="small"
            placeholder="NC, CMP, NP, DELAY, UNK"
            value={proposedPhase}
            onChange={(e) => setProposedPhase(e.target.value)}
            disabled={saving || !!success}
            autoFocus
          />

          {error ? (
            <Typography variant="caption" color="error">
              {error}
            </Typography>
          ) : null}
          {success ? (
            <Alert severity="success" sx={{ py: 0.25 }}>
              {success}
            </Alert>
          ) : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Close</Button>
        <Button variant="contained" onClick={handleConfirm} disabled={saving || !!success}>
          {saving ? 'Saving…' : 'Confirm'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default PhaseCorrectionDialog
