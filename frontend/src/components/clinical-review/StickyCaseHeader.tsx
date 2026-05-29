import { Alert, Box, Button, Chip, CircularProgress, Paper, Stack, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'

import type { CaseSummary } from '../../services/api'
import { formatStatus, statusChipColor } from './reviewUi'

interface StickyCaseHeaderProps {
  activeQcStatus: string | null
  caseId: string
  caseWarningCount: number
  currentCaseQueued: boolean
  datasetId: string
  dossierPath: string
  nextCase: CaseSummary | null
  onNext: () => void
  onPrevious: () => void
  previousCase: CaseSummary | null
  selectedCase: CaseSummary | null
  volumeLoading: boolean
  worklistPath: string
}

function StickyCaseHeader({
  activeQcStatus,
  caseId,
  caseWarningCount,
  currentCaseQueued,
  datasetId,
  dossierPath,
  nextCase,
  onNext,
  onPrevious,
  previousCase,
  selectedCase,
  volumeLoading,
  worklistPath,
}: StickyCaseHeaderProps) {
  return (
    <Paper
      elevation={0}
      data-testid="sticky-case-header"
      sx={{
        flexShrink: 0,
        px: { xs: 1.5, md: 2 },
        py: { xs: 1.1, md: 1.25 },
        borderColor: caseWarningCount > 0 ? 'warning.dark' : 'divider',
        backgroundColor: 'rgba(18, 18, 18, 0.94)',
        backdropFilter: 'blur(16px)',
        position: { xs: 'sticky', lg: 'static' },
        top: { xs: 72, md: 80 },
        zIndex: 12,
      }}
    >
      <Stack
        direction={{ xs: 'column', lg: 'row' }}
        spacing={1.25}
        alignItems={{ lg: 'center' }}
        justifyContent="space-between"
      >
        <Stack spacing={0.65} sx={{ minWidth: 0 }}>
          <Typography variant="overline" color="text.secondary">
            Case Review
          </Typography>
          <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography variant="h4" sx={{ lineHeight: 1 }}>
              {caseId}
            </Typography>
            <Chip label={datasetId} color="primary" size="small" variant="outlined" />
            <Chip
              label={selectedCase?.patient_id ?? 'Unknown patient'}
              size="small"
              variant="outlined"
            />
            <Chip label={selectedCase?.group ?? 'Unknown group'} size="small" variant="outlined" />
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
            <Chip
              label={currentCaseQueued ? 'Queued' : 'Not queued'}
              color={currentCaseQueued ? 'warning' : 'default'}
              size="small"
              variant={currentCaseQueued ? 'filled' : 'outlined'}
            />
            {volumeLoading ? <CircularProgress size={18} /> : null}
          </Stack>
        </Stack>

        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
          <Button size="small" variant="outlined" component={RouterLink} to={worklistPath}>
            Worklist
          </Button>
          <Button size="small" variant="outlined" component={RouterLink} to={dossierPath}>
            Case Dossier
          </Button>
          <Button size="small" variant="outlined" disabled={!previousCase} onClick={onPrevious}>
            Previous
          </Button>
          <Button size="small" variant="contained" disabled={!nextCase} onClick={onNext}>
            Next case
          </Button>
        </Stack>
      </Stack>
      {!selectedCase ? (
        <Box sx={{ mt: 1 }}>
          <Alert severity="warning">This case is not present in the current worklist response.</Alert>
        </Box>
      ) : null}
    </Paper>
  )
}

export default StickyCaseHeader
