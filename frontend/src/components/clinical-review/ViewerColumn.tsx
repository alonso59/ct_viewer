import { Alert, Box, Stack } from '@mui/material'
import type { ReactNode } from 'react'

interface ViewerColumnProps {
  drawerTabs: ReactNode
  inventoryError: string | null
  inventoryLoading: boolean
  mprViewer: ReactNode
  noSource: boolean
  scopeLabel: string
  sourceStrip: ReactNode
  toolbar: ReactNode
}

function ViewerColumn({
  drawerTabs,
  inventoryError,
  inventoryLoading,
  mprViewer,
  noSource,
  scopeLabel,
  sourceStrip,
  toolbar,
}: ViewerColumnProps) {
  return (
    <Stack
      data-testid="viewer-column"
      spacing={0.9}
      sx={{
        height: { lg: '100%' },
        minHeight: 0,
        minWidth: 0,
        overflow: { xs: 'visible', lg: 'hidden' },
      }}
    >
      {toolbar}
      {inventoryError ? <Alert severity="error">{inventoryError}</Alert> : null}
      {!inventoryError && noSource && !inventoryLoading ? (
        <Alert severity="warning">
          No {scopeLabel} source is available for the selected phase.
        </Alert>
      ) : null}
      {sourceStrip}
      <Box
        data-testid="mpr-viewer-region"
        sx={{
          flex: { lg: 1 },
          minHeight: { xs: 520, lg: 0 },
          minWidth: 0,
          overflow: 'hidden',
        }}
      >
        {mprViewer}
      </Box>
      {drawerTabs}
    </Stack>
  )
}

export default ViewerColumn
