import { Alert, Chip, Stack, Typography } from '@mui/material'

import type { CurationDecision } from '../../services/api'
import { formatDate, formatStatus, statusChipColor } from './reviewUi'

interface HistoryTabProps {
  decisions: CurationDecision[]
  error: string | null
  selectedRowId: string | null
}

function HistoryTab({ decisions, error, selectedRowId }: HistoryTabProps) {
  const ordered = [...decisions].sort((left, right) =>
    right.reviewed_at.localeCompare(left.reviewed_at),
  )

  return (
    <Stack spacing={1} data-testid="curation-history-panel">
      {error ? <Alert severity="warning">{error}</Alert> : null}
      {!error && ordered.length === 0 ? (
        <Alert severity="info">No prior curation decisions for this case.</Alert>
      ) : null}
      {ordered.map((decision) => {
        const selectedSource = decision.row_id === selectedRowId
        return (
          <Alert
            key={decision.review_id}
            severity={selectedSource ? 'success' : 'info'}
            variant={selectedSource ? 'filled' : 'outlined'}
            sx={{ alignItems: 'stretch' }}
          >
            <Stack spacing={0.55}>
              <Stack direction="row" spacing={0.6} flexWrap="wrap" useFlexGap>
                <Chip
                  label={formatStatus(decision.status)}
                  color={statusChipColor(decision.status)}
                  size="small"
                />
                <Chip label={formatStatus(decision.target)} size="small" variant="outlined" />
                <Chip label={formatStatus(decision.priority)} size="small" variant="outlined" />
                {selectedSource ? <Chip label="Selected source" size="small" /> : null}
              </Stack>
              <Typography variant="body2">{decision.comment || 'No comment.'}</Typography>
              <Typography variant="caption">
                {decision.reviewer || 'Unknown reviewer'} - {formatDate(decision.reviewed_at)}
              </Typography>
            </Stack>
          </Alert>
        )
      })}
    </Stack>
  )
}

export default HistoryTab
