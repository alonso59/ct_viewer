import { Box, Stack } from '@mui/material'
import type { ReactNode } from 'react'

interface ClinicalReviewShellProps {
  caseRail: ReactNode
  decisionPanel: ReactNode
  header: ReactNode
  toast: ReactNode
  viewerColumn: ReactNode
}

function ClinicalReviewShell({
  caseRail,
  decisionPanel,
  header,
  toast,
  viewerColumn,
}: ClinicalReviewShellProps) {
  return (
    <Stack
      data-testid="clinical-review-shell"
      spacing={1.25}
      sx={{
        minWidth: 0,
        height: { xs: 'auto', lg: 'calc(100vh - 132px)' },
        minHeight: { lg: 0 },
      }}
    >
      {header}

      <Box
        data-testid="case-review-cockpit"
        sx={{
          display: 'grid',
          gridTemplateColumns: {
            xs: '1fr',
            lg: '72px minmax(0, 1fr) minmax(320px, 340px)',
          },
          '@media (min-width: 1600px)': {
            gridTemplateColumns: '280px minmax(0, 1fr) 380px',
          },
          gap: 1.25,
          flex: { lg: 1 },
          minHeight: { lg: 0 },
          alignItems: { xs: 'stretch', lg: 'stretch' },
          overflow: { xs: 'visible', lg: 'hidden' },
        }}
      >
        <Box sx={{ minWidth: 0, minHeight: 0 }}>{caseRail}</Box>
        <Box sx={{ minWidth: 0, minHeight: 0 }}>{viewerColumn}</Box>
        <Box sx={{ minWidth: 0, minHeight: 0 }}>{decisionPanel}</Box>
      </Box>

      {toast}
    </Stack>
  )
}

export default ClinicalReviewShell
