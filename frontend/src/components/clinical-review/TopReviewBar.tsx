import { Button, Chip, CircularProgress, Paper, Stack, Tooltip, Typography } from '@mui/material'

import type { CaseSummary } from '../../services/api'
import { formatStatus, statusChipColor } from './reviewUi'

interface TopReviewBarProps {
  activeQcStatus: string | null
  caseId: string
  caseWarningCount: number
  currentCaseQueued: boolean
  datasetId: string
  onOpenHelp: () => void
  selectedCase: CaseSummary | null
  sourceLabel: string
  volumeLoading: boolean
}

function TopReviewBar({
  activeQcStatus,
  caseId,
  caseWarningCount,
  currentCaseQueued,
  datasetId,
  onOpenHelp,
  selectedCase,
  sourceLabel,
  volumeLoading,
}: TopReviewBarProps) {
  return (
    <Paper
      elevation={0}
      data-testid="top-review-bar"
      sx={{
        flexShrink: 0,
        px: 1.5,
        py: 0.4,
        borderColor: caseWarningCount > 0 ? 'warning.dark' : 'divider',
        backgroundColor: 'rgba(18, 18, 18, 0.96)',
      }}
    >
      <Stack direction="row" spacing={0.8} alignItems="center" sx={{ minWidth: 0 }}>
        <Stack spacing={0} sx={{ minWidth: 0, flex: 1 }}>
          <Stack direction="row" spacing={0.7} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography variant="h6" sx={{ lineHeight: 1.05 }}>
              {caseId}
            </Typography>
            <Chip label={datasetId} color="primary" size="small" variant="outlined" />
            <Chip label={selectedCase?.patient_id ?? 'Unknown patient'} size="small" variant="outlined" />
            <Chip label={sourceLabel} color="primary" size="small" variant="outlined" />
            <Chip
              label={formatStatus(activeQcStatus)}
              color={statusChipColor(activeQcStatus)}
              size="small"
              variant={activeQcStatus ? 'filled' : 'outlined'}
            />
            <Chip
              label={`Warnings ${caseWarningCount}`}
              color={caseWarningCount > 0 ? 'warning' : 'default'}
              size="small"
              variant={caseWarningCount > 0 ? 'filled' : 'outlined'}
            />
            {currentCaseQueued ? <Chip label="Queued" color="warning" size="small" /> : null}
            {volumeLoading ? <CircularProgress size={16} /> : null}
          </Stack>
        </Stack>
        <Tooltip title="Keyboard shortcuts: N next case, A accept, C needs correction, R reject, Space next slice">
          <Button size="small" variant="text" onClick={onOpenHelp} sx={{ px: 1, py: 0.25, minWidth: 0, fontSize: 12 }}>
            Help
          </Button>
        </Tooltip>
      </Stack>
    </Paper>
  )
}

export default TopReviewBar
