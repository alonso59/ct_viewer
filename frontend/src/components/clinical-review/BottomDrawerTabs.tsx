import { Box, Paper, Stack, Tab, Tabs, TableContainer, Typography } from '@mui/material'
import { useState, type ReactNode } from 'react'

import type {
  CaseDossier,
  CaseInventoryRow,
  CurationDecision,
  Scope,
} from '../../services/api'
import HistoryTab from './HistoryTab'
import InventoryTab from './InventoryTab'
import MetadataTab from './MetadataTab'
import WarningsTab from './WarningsTab'

interface BottomDrawerTabsProps {
  curationHistory: CurationDecision[]
  curationHistoryError: string | null
  dossier: CaseDossier | null
  dossierPath: string
  onSelectSource: (row: CaseInventoryRow, scope: Scope) => void
  queueButton: ReactNode
  rows: CaseInventoryRow[]
  scope: Scope
  selectedRow: CaseInventoryRow | null
  sourceLabel: string
}

type DrawerTab = 'inventory' | 'warnings' | 'history' | 'metadata'

function BottomDrawerTabs({
  curationHistory,
  curationHistoryError,
  dossier,
  dossierPath,
  onSelectSource,
  queueButton,
  rows,
  scope,
  selectedRow,
  sourceLabel,
}: BottomDrawerTabsProps) {
  const [tab, setTab] = useState<DrawerTab>('inventory')

  return (
    <Paper
      elevation={0}
      data-testid="bottom-drawer-tabs"
      sx={{
        flexShrink: 0,
        minHeight: 0,
        height: { xs: 'auto', lg: 214 },
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
        sx={{
          px: 1,
          borderBottom: '1px solid',
          borderColor: 'divider',
          minHeight: 42,
        }}
      >
        <Tabs
          value={tab}
          onChange={(_, value: DrawerTab) => setTab(value)}
          variant="scrollable"
          allowScrollButtonsMobile
        >
          <Tab label="Inventory" value="inventory" />
          <Tab label="Warnings" value="warnings" />
          <Tab label="History" value="history" />
          <Tab label="Metadata" value="metadata" />
        </Tabs>
        <Box sx={{ display: { xs: 'none', md: 'block' }, flexShrink: 0 }}>{queueButton}</Box>
      </Stack>

      <Box
        sx={{
          flex: 1,
          minHeight: 0,
          overflow: 'auto',
          p: 1,
          backgroundColor: 'rgba(255,255,255,0.015)',
        }}
      >
        {tab === 'inventory' ? (
          <Stack spacing={0.75}>
            <Typography variant="caption" color="text.secondary">
              Displayed: {sourceLabel}
            </Typography>
            <TableContainer>
              <InventoryTab
                onSelectSource={onSelectSource}
                rows={rows}
                scope={scope}
                selectedRowId={selectedRow?.row_id ?? null}
              />
            </TableContainer>
          </Stack>
        ) : null}
        {tab === 'warnings' ? <WarningsTab rows={rows} selectedRow={selectedRow} /> : null}
        {tab === 'history' ? (
          <HistoryTab
            decisions={curationHistory}
            error={curationHistoryError}
            selectedRowId={selectedRow?.row_id ?? null}
          />
        ) : null}
        {tab === 'metadata' ? <MetadataTab dossier={dossier} dossierPath={dossierPath} /> : null}
      </Box>
    </Paper>
  )
}

export default BottomDrawerTabs
