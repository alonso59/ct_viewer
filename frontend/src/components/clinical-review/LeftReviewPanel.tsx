import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  SvgIcon,
  Typography,
} from '@mui/material'
import { useState } from 'react'

import type { CaseInventoryRow, CaseSummary, CurationDecision, Scope } from '../../services/api'
import CaseNavigator from './CaseNavigator'
import HistoryTab from './HistoryTab'
import InventoryTab from './InventoryTab'
import PhaseCorrectionDialog from './PhaseCorrectionDialog'
import RightQcPanel from './RightQcPanel'
import SourceNavigator from './SourceNavigator'
import WarningBadges from './WarningBadges'
import WarningsTab from './WarningsTab'

type ModuleId = 'review' | 'sources' | 'qc' | 'case-data' | 'warnings' | 'history'

const MODULE_OPTIONS: Array<{ value: ModuleId; label: string }> = [
  { value: 'sources', label: 'Data' },
  { value: 'qc', label: 'QC' },
  { value: 'case-data', label: 'Case Data' },
  { value: 'warnings', label: 'Warnings' },
  { value: 'history', label: 'History' },
]

function ExpandMoreIcon(props: React.ComponentProps<typeof SvgIcon>) {
  return (
    <SvgIcon {...props} viewBox="0 0 24 24">
      <path d="M7.41 8.59 12 13.17l4.59-4.58L18 10l-6 6-6-6z" />
    </SvgIcon>
  )
}

interface LeftReviewPanelProps {
  caseError: string | null
  caseQueued: boolean
  cases: CaseSummary[]
  curationHistory: CurationDecision[]
  curationHistoryError: string | null
  currentCaseId: string
  datasetId: string
  latestDecision: CurationDecision | null
  missingSegBlocked: boolean
  noSource: boolean
  onError: (message: string) => void
  onOpenCaseData: () => void
  onSaved: (decision: CurationDecision, queued: boolean, advance: boolean) => void
  onSelectCase: (caseId: string) => void
  onSelectSource: (row: CaseInventoryRow, scope: Scope) => void
  queuedCaseIds: string[]
  rows: CaseInventoryRow[]
  scope: Scope
  selectedCase: CaseSummary | null
  selectedPhase: CaseInventoryRow['canonical_phase'] | null
  selectedRow: CaseInventoryRow | null
  sourceLabel: string
}

function LeftReviewPanel({
  caseError,
  caseQueued,
  cases,
  curationHistory,
  curationHistoryError,
  currentCaseId,
  datasetId,
  latestDecision,
  missingSegBlocked,
  noSource,
  onError,
  onOpenCaseData,
  onSaved,
  onSelectCase,
  onSelectSource,
  queuedCaseIds,
  rows,
  scope,
  selectedCase,
  selectedPhase,
  selectedRow,
  sourceLabel,
}: LeftReviewPanelProps) {
  const [activeModule, setActiveModule] = useState<ModuleId>('sources')
  const [phaseDialogOpen, setPhaseDialogOpen] = useState(false)
  const [phaseDialogScanIdx, setPhaseDialogScanIdx] = useState<string | null>(null)
  const totalWarnings = rows.reduce((sum, row) => sum + row.qc_warnings.length, 0)

  function openPhaseDialog(scanIdx?: string | null) {
    setPhaseDialogScanIdx(scanIdx !== undefined ? scanIdx : (selectedRow?.scan_idx ?? null))
    setPhaseDialogOpen(true)
  }

  function handlePhaseSaved(decision: CurationDecision) {
    onSaved(decision, true, false)
  }

  return (
    <Paper
      elevation={0}
      data-testid="left-review-panel"
      sx={{
        width: 'clamp(340px, 27vw, 480px)',
        minWidth: 340,
        height: '100%',
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        backgroundColor: 'rgba(18, 18, 18, 0.96)',
      }}
    >
      {/* ── Module selector ── */}
      <Box sx={{ flexShrink: 0, px: 1.1, pt: 1.1, pb: 0.75 }}>
        <FormControl fullWidth size="small">
          <InputLabel id="module-selector-label">Module</InputLabel>
          <Select
            labelId="module-selector-label"
            label="Module"
            value={activeModule}
            onChange={(e) => setActiveModule(e.target.value as ModuleId)}
            data-testid="module-selector"
            renderValue={(value) => {
              const found = MODULE_OPTIONS.find((opt) => opt.value === value)
              return (
                <Stack direction="row" spacing={0.75} alignItems="center">
                  <Typography variant="body2">{found?.label ?? value}</Typography>
                  {value === 'warnings' && totalWarnings > 0 ? (
                    <Chip label={totalWarnings} size="small" color="warning" sx={{ height: 16, fontSize: 10 }} />
                  ) : null}
                </Stack>
              )
            }}
          >
            {MODULE_OPTIONS.map((opt) => (
              <MenuItem key={opt.value} value={opt.value}>
                <Stack direction="row" spacing={0.75} alignItems="center" sx={{ width: '100%' }}>
                  <Typography variant="body2" sx={{ flex: 1 }}>
                    {opt.label}
                  </Typography>
                  {opt.value === 'warnings' && totalWarnings > 0 ? (
                    <Chip label={totalWarnings} size="small" color="warning" sx={{ height: 16, fontSize: 10 }} />
                  ) : null}
                </Stack>
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Box>

      {/* ── Module content (scrollable) ── */}
      <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto', px: 1.1, pb: 1.1 }}>

        {/* Review module removed — content moved to sticky footer */}

        {/* Sources / Data module */}
        {activeModule === 'sources' ? (
          <Stack spacing={1.25}>
            <SourceNavigator
              onSelectSource={onSelectSource}
              rows={rows}
              scope={scope}
              selectedPhase={selectedPhase}
              selectedRow={selectedRow}
            />
            <Accordion
              disableGutters
              data-testid="inventory-detail"
              sx={{
                border: '1px solid',
                borderColor: 'rgba(255,255,255,0.12)',
                borderRadius: 1,
                backgroundColor: 'rgba(255,255,255,0.025)',
                '&:before': { display: 'none' },
              }}
            >
              <AccordionSummary
                expandIcon={<ExpandMoreIcon fontSize="small" />}
                sx={{
                  minHeight: 38,
                  px: 1,
                  '& .MuiAccordionSummary-content': { my: 0.75 },
                }}
              >
                <Stack spacing={0.15}>
                  <Typography variant="body2" fontWeight={800}>
                    Inventory detail
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Paths, QC state, and phase correction
                  </Typography>
                </Stack>
              </AccordionSummary>
              <AccordionDetails sx={{ px: 1, pt: 0, pb: 1 }}>
                <InventoryTab
                  onSelectSource={onSelectSource}
                  onPhaseCorrection={openPhaseDialog}
                  rows={rows}
                  scope={scope}
                  selectedRowId={selectedRow?.row_id ?? null}
                />
              </AccordionDetails>
            </Accordion>
          </Stack>
        ) : null}

        {/* QC module */}
        {activeModule === 'qc' ? (
          <RightQcPanel
            caseId={currentCaseId}
            caseQueued={caseQueued}
            datasetId={datasetId}
            latestDecision={latestDecision}
            missingSegBlocked={missingSegBlocked}
            noSource={noSource}
            onError={onError}
            onSaved={onSaved}
            row={selectedRow}
            scope={scope}
            sourceLabel={sourceLabel}
          />
        ) : null}

        {/* Case Data module */}
        {activeModule === 'case-data' ? (
          <Stack spacing={1.25}>
            <Typography variant="overline" color="text.secondary" sx={{ lineHeight: 1 }}>
              Case
            </Typography>
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
              <Chip label={currentCaseId} size="small" color="primary" variant="outlined" />
              {selectedCase?.patient_id ? (
                <Chip label={selectedCase.patient_id} size="small" variant="outlined" />
              ) : null}
              <Chip label={datasetId} size="small" variant="outlined" />
            </Stack>
            <Stack spacing={0.75}>
              <Button
                variant="outlined"
                fullWidth
                onClick={onOpenCaseData}
                data-testid="case-data-action"
              >
                Open Case Data
              </Button>
              <Button variant="outlined" fullWidth onClick={() => openPhaseDialog()}>
                Phase correction
              </Button>
            </Stack>
          </Stack>
        ) : null}

        {/* Warnings module */}
        {activeModule === 'warnings' ? (
          <Stack spacing={1.25}>
            <WarningBadges rows={rows} selectedRow={selectedRow} />
            <WarningsTab rows={rows} selectedRow={selectedRow} />
          </Stack>
        ) : null}

        {/* History module */}
        {activeModule === 'history' ? (
          <HistoryTab
            decisions={curationHistory}
            error={curationHistoryError}
            selectedRowId={selectedRow?.row_id ?? null}
          />
        ) : null}

      </Box>

      {/* ── Sticky footer ── */}
      <Stack
        spacing={0.75}
        sx={{
          flexShrink: 0,
          p: 1.1,
          borderTop: '1px solid',
          borderColor: 'divider',
          backgroundColor: 'rgba(10, 10, 10, 0.94)',
        }}
      >
        {/* Review context row */}
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          {selectedRow ? (
            <Chip
              label={sourceLabel}
              size="small"
              color={scope === 'voi' ? 'success' : 'primary'}
              variant="outlined"
              sx={{ maxWidth: '100%' }}
            />
          ) : null}
          {totalWarnings > 0 ? (
            <Button
              size="small"
              variant="outlined"
              color="warning"
              onClick={() => setActiveModule('warnings')}
            >
              {totalWarnings} warning{totalWarnings > 1 ? 's' : ''}
            </Button>
          ) : null}
          <Button
            size="small"
            variant="outlined"
            onClick={() => setActiveModule('qc')}
            data-testid="go-to-qc-button"
          >
            QC →
          </Button>
        </Stack>
        <CaseNavigator
          cases={cases}
          currentCaseId={currentCaseId}
          error={caseError}
          onSelect={onSelectCase}
          queuedCaseIds={queuedCaseIds}
        />
      </Stack>

      <PhaseCorrectionDialog
        open={phaseDialogOpen}
        caseId={currentCaseId}
        datasetId={datasetId}
        rows={rows}
        initialScanIdx={phaseDialogScanIdx}
        onClose={() => setPhaseDialogOpen(false)}
        onSaved={handlePhaseSaved}
      />
    </Paper>
  )
}

export default LeftReviewPanel
