import { Box, Paper, Stack, Tab, Tabs, TableContainer, Typography } from '@mui/material'
import { useState } from 'react'

import type { CaseInventoryRow, CurationDecision, Scope } from '../../services/api'
import HistoryTab from './HistoryTab'
import InventoryTab from './InventoryTab'
import WarningsTab from './WarningsTab'

interface BottomDrawerProps {
  curationHistory: CurationDecision[]
  curationHistoryError: string | null
  onSelectSource: (row: CaseInventoryRow, scope: Scope) => void
  rows: CaseInventoryRow[]
  scope: Scope
  selectedRow: CaseInventoryRow | null
  sourceLabel: string
}

type DrawerTab = 'inventory' | 'warnings' | 'history'

function BottomDrawer({
  curationHistory,
  curationHistoryError,
  onSelectSource,
  rows,
  scope,
  selectedRow,
  sourceLabel,
}: BottomDrawerProps) {
  const [tab, setTab] = useState<DrawerTab>('inventory')

  return (
    <Paper
      elevation={0}
      data-testid="bottom-drawer"
      sx={{
        flexShrink: 0,
        height: { md: 168, lg: 176 },
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <Stack
        direction="row"
        spacing={1}
        alignItems="center"
        justifyContent="space-between"
        sx={{ px: 1, minHeight: 38, borderBottom: '1px solid', borderColor: 'divider' }}
      >
        <Tabs value={tab} onChange={(_, value: DrawerTab) => setTab(value)} variant="scrollable">
          <Tab label="Inventory" value="inventory" />
          <Tab label="Warnings" value="warnings" />
          <Tab label="History" value="history" />
        </Tabs>
        <Typography variant="caption" color="text.secondary" sx={{ display: { xs: 'none', sm: 'block' } }}>
          {sourceLabel}
        </Typography>
      </Stack>

      <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto', p: 1, backgroundColor: 'rgba(255,255,255,0.015)' }}>
        {tab === 'inventory' ? (
          <TableContainer>
            <InventoryTab
              onSelectSource={onSelectSource}
              rows={rows}
              scope={scope}
              selectedRowId={selectedRow?.row_id ?? null}
            />
          </TableContainer>
        ) : null}
        {tab === 'warnings' ? <WarningsTab rows={rows} selectedRow={selectedRow} /> : null}
        {tab === 'history' ? (
          <HistoryTab
            decisions={curationHistory}
            error={curationHistoryError}
            selectedRowId={selectedRow?.row_id ?? null}
          />
        ) : null}
      </Box>
    </Paper>
  )
}

export default BottomDrawer
