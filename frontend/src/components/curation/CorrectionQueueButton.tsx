import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'

import {
  apiClient,
  getApiErrorMessage,
  type CorrectionQueueResponse,
} from '../../services/api'

interface CorrectionQueueButtonProps {
  caseId?: string
  datasetId: string
  refreshKey?: number
  showExportLink?: boolean
}

function CorrectionQueueButton({
  caseId,
  datasetId,
  refreshKey = 0,
  showExportLink = false,
}: CorrectionQueueButtonProps) {
  const [queue, setQueue] = useState<CorrectionQueueResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let active = true
    apiClient
      .listCorrectionQueue(datasetId)
      .then((response) => {
        if (!active) {
          return
        }
        setQueue(response)
        setError(null)
      })
      .catch((requestError) => {
        if (!active) {
          return
        }
        setQueue(null)
        setError(getApiErrorMessage(requestError))
      })
    return () => {
      active = false
    }
  }, [datasetId, refreshKey])

  const count = queue?.items.length ?? 0
  const currentCaseQueued = Boolean(
    caseId && queue?.items.some((item) => item.case_id === caseId),
  )
  const exportUrl = `/api/datasets/${datasetId}/curation/correction-queue.csv`

  return (
    <>
      <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
        {caseId ? (
          <Chip
            label={currentCaseQueued ? 'Current case queued' : 'Current case not queued'}
            color={currentCaseQueued ? 'warning' : 'default'}
            size="small"
            variant={currentCaseQueued ? 'filled' : 'outlined'}
          />
        ) : null}
        <Button
          size="small"
          variant="outlined"
          onClick={() => setOpen(true)}
          endIcon={<Chip label={count} size="small" />}
        >
          Correction Queue
        </Button>
        {showExportLink ? (
          <Button
            component="a"
            href={exportUrl}
            rel="noreferrer"
            size="small"
            target="_blank"
            variant="text"
          >
            Export CSV
          </Button>
        ) : null}
      </Stack>
      <Dialog fullWidth maxWidth="lg" open={open} onClose={() => setOpen(false)}>
        <DialogTitle>Correction Queue</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5}>
            {error ? <Alert severity="warning">{error}</Alert> : null}
            {!error && count === 0 ? (
              <Alert severity="info">No queued correction items.</Alert>
            ) : null}
            {count > 0 ? (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Case</TableCell>
                      <TableCell>Target</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Priority</TableCell>
                      <TableCell>Context</TableCell>
                      <TableCell>Reviewer</TableCell>
                      <TableCell>Reviewed</TableCell>
                      <TableCell>Comment</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {queue?.items.map((item) => (
                      <TableRow key={item.review_id}>
                        <TableCell>{item.case_id}</TableCell>
                        <TableCell>{formatLabel(item.target)}</TableCell>
                        <TableCell>{formatLabel(item.status)}</TableCell>
                        <TableCell>{formatLabel(item.priority)}</TableCell>
                        <TableCell>
                          {[
                            item.canonical_phase,
                            item.scan_idx ? `scan ${item.scan_idx}` : null,
                            item.side,
                            item.scope,
                          ]
                            .filter(Boolean)
                            .join(' / ') || '-'}
                        </TableCell>
                        <TableCell>{item.reviewer || '-'}</TableCell>
                        <TableCell>{formatDate(item.reviewed_at)}</TableCell>
                        <TableCell>
                          <Typography variant="body2" sx={{ maxWidth: 220 }}>
                            {item.comment || '-'}
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            ) : null}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button component="a" href={exportUrl} target="_blank" rel="noreferrer">
            Export CSV
          </Button>
          <Button onClick={() => setOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

function formatLabel(value: string | null | undefined): string {
  if (!value) {
    return '-'
  }
  return value.replaceAll('_', ' ')
}

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return '-'
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return parsed.toLocaleString()
}

export default CorrectionQueueButton
