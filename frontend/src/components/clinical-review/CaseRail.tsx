import { Alert, Button, Chip, Paper, Stack, Typography } from '@mui/material'

import type { CaseSummary } from '../../services/api'
import { compactCaseLabel, formatStatus, statusChipColor } from './reviewUi'

interface CaseRailProps {
  cases: CaseSummary[]
  currentCaseId: string
  error: string | null
  expanded: boolean
  onSelect: (caseId: string) => void
  onToggleExpanded: () => void
  queuedCaseIds: string[]
}

function CaseRail({
  cases,
  currentCaseId,
  error,
  expanded,
  onSelect,
  onToggleExpanded,
  queuedCaseIds,
}: CaseRailProps) {
  const queued = new Set(queuedCaseIds)

  return (
    <Paper
      elevation={0}
      data-testid="case-rail"
      sx={{
        height: { lg: '100%' },
        minHeight: 0,
        p: { xs: 1.25, lg: expanded ? 1.1 : 0.65 },
        overflow: 'auto',
      }}
    >
      <Stack spacing={0.8}>
        <Stack
          direction={{ xs: 'row', lg: expanded ? 'row' : 'column' }}
          spacing={0.75}
          alignItems="center"
          justifyContent="space-between"
        >
          <Typography
            variant="overline"
            color="text.secondary"
            sx={{
              display: { lg: expanded ? 'block' : 'none' },
              '@media (min-width: 1600px)': { display: 'block' },
            }}
          >
            Case Rail
          </Typography>
          <Chip label={cases.length} size="small" variant="outlined" />
          <Button
            size="small"
            variant="text"
            onClick={onToggleExpanded}
            sx={{
              minWidth: 0,
              px: { lg: expanded ? 1 : 0.75 },
              display: { xs: 'none', lg: 'inline-flex' },
              '@media (min-width: 1600px)': { display: 'none' },
            }}
          >
            {expanded ? 'Compact' : 'Open'}
          </Button>
        </Stack>
        {error ? <Alert severity="warning">{error}</Alert> : null}
        {cases.slice(0, 240).map((entry) => {
          const selected = entry.case_id === currentCaseId
          const isQueued = queued.has(entry.case_id)
          return (
            <Button
              key={entry.case_id}
              data-testid="case-rail-item"
              onClick={() => onSelect(entry.case_id)}
              variant={selected ? 'contained' : 'text'}
              sx={{
                justifyContent: { xs: 'space-between', lg: expanded ? 'space-between' : 'center' },
                borderRadius: 1,
                px: { xs: 1, lg: expanded ? 1 : 0.45 },
                py: 0.65,
                textAlign: 'left',
                minWidth: 0,
                border: selected ? '1px solid' : '1px solid transparent',
                borderColor: selected ? 'primary.main' : 'transparent',
                '@media (min-width: 1600px)': {
                  justifyContent: 'space-between',
                  px: 1,
                },
              }}
            >
              <Stack spacing={0.25} sx={{ minWidth: 0 }}>
                <Typography
                  component="span"
                  variant="body2"
                  fontWeight={800}
                  sx={{
                    maxWidth: '100%',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {expanded ? entry.case_id : compactCaseLabel(entry.case_id)}
                </Typography>
                <Typography
                  component="span"
                  variant="caption"
                  color={selected ? 'inherit' : 'text.secondary'}
                  sx={{
                    display: { lg: expanded ? 'block' : 'none' },
                    '@media (min-width: 1600px)': { display: 'block' },
                  }}
                >
                  {formatStatus(entry.latest_curation_status)}
                </Typography>
              </Stack>
              <Stack
                direction="row"
                spacing={0.45}
                sx={{
                  display: { lg: expanded ? 'flex' : 'none' },
                  '@media (min-width: 1600px)': { display: 'flex' },
                }}
              >
                {isQueued ? <Chip label="Q" color="warning" size="small" /> : null}
                <Chip
                  label={entry.warning_count}
                  color={entry.warning_count > 0 ? 'warning' : statusChipColor(entry.latest_curation_status)}
                  size="small"
                  variant={entry.warning_count > 0 ? 'filled' : 'outlined'}
                />
              </Stack>
              {!expanded && entry.warning_count > 0 ? (
                <Chip
                  label={entry.warning_count}
                  color="warning"
                  size="small"
                  sx={{
                    display: { xs: 'inline-flex', lg: 'inline-flex' },
                    '@media (min-width: 1600px)': { display: 'none' },
                  }}
                />
              ) : null}
            </Button>
          )
        })}
      </Stack>
    </Paper>
  )
}

export default CaseRail
