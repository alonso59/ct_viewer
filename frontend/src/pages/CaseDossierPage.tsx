import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link as RouterLink, useParams, useSearchParams } from 'react-router-dom'

import {
  apiClient,
  getApiErrorMessage,
  type CaseDossier,
  type CaseInventoryRow,
  type CaseSummary,
  type CorrectionQueueResponse,
  type CurationDecision,
} from '../services/api'
import {
  formatDate,
  formatStatus,
  pathStatusLabel,
  sortInventoryRows,
  statusChipColor,
} from '../components/clinical-review/reviewUi'

interface DossierState {
  cases: CaseSummary[]
  dossier: CaseDossier | null
  error: string | null
  history: CurationDecision[]
  inventory: CaseInventoryRow[]
  loading: boolean
  queue: CorrectionQueueResponse | null
}

function CaseDossierPage() {
  const { dsid = 'unknown-dataset', caseId = 'unknown-case' } = useParams<{
    dsid: string
    caseId: string
  }>()
  const [searchParams] = useSearchParams()
  const [state, setState] = useState<DossierState>({
    cases: [],
    dossier: null,
    error: null,
    history: [],
    inventory: [],
    loading: true,
    queue: null,
  })

  useEffect(() => {
    let active = true
    setState((current) => ({ ...current, loading: true, error: null }))
    Promise.all([
      apiClient.listCases(dsid),
      apiClient.listCaseInventory(dsid, caseId),
      apiClient.getCaseDossier(dsid, caseId),
      apiClient.getCurationHistory(dsid, caseId),
      apiClient.listCorrectionQueue(dsid),
    ])
      .then(([cases, inventory, dossier, history, queue]) => {
        if (!active) {
          return
        }
        setState({
          cases,
          dossier,
          error: null,
          history,
          inventory,
          loading: false,
          queue,
        })
      })
      .catch((error) => {
        if (!active) {
          return
        }
        setState((current) => ({
          ...current,
          error: getApiErrorMessage(error),
          loading: false,
        }))
      })
    return () => {
      active = false
    }
  }, [caseId, dsid])

  const selectedRowId = searchParams.get('row_id')
  const selectedScope = searchParams.get('scope')
  const reviewPath = `/datasets/${dsid}/cases/${caseId}/review${buildReviewQuery(
    selectedRowId,
    selectedScope,
  )}`
  const caseSummary = state.cases.find((entry) => entry.case_id === caseId) ?? null
  const sortedInventory = useMemo(() => sortInventoryRows(state.inventory), [state.inventory])
  const selectedRow = selectedRowId
    ? sortedInventory.find((row) => row.row_id === selectedRowId) ?? null
    : null
  const warnings = sortedInventory.flatMap((row) =>
    row.qc_warnings.map((warning) => ({ ...warning, row })),
  )
  const queueItems = state.queue?.items.filter((item) => item.case_id === caseId) ?? []
  const latestDecision =
    [...state.history].sort((left, right) => right.reviewed_at.localeCompare(left.reviewed_at))[0] ??
    null

  return (
    <Stack spacing={2.25} data-testid="case-dossier-page">
      <Paper elevation={0} sx={{ p: { xs: 2, md: 2.5 } }}>
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          spacing={1.5}
          alignItems={{ md: 'center' }}
          justifyContent="space-between"
        >
          <Stack spacing={0.6} sx={{ minWidth: 0 }}>
            <Typography variant="overline" color="text.secondary">
              Case Dossier
            </Typography>
            <Stack direction="row" spacing={0.8} alignItems="center" flexWrap="wrap" useFlexGap>
              <Typography variant="h3">{caseId}</Typography>
              <Chip label={dsid} color="primary" variant="outlined" />
              <Chip label={caseSummary?.patient_id ?? 'Unknown patient'} variant="outlined" />
              <Chip label={caseSummary?.group ?? 'Unknown group'} variant="outlined" />
              <Chip
                label={formatStatus(caseSummary?.latest_curation_status ?? latestDecision?.status)}
                color={statusChipColor(caseSummary?.latest_curation_status ?? latestDecision?.status)}
                variant={caseSummary?.latest_curation_status || latestDecision ? 'filled' : 'outlined'}
              />
            </Stack>
            <Typography variant="body2" color="text.secondary">
              Categorized inspection of database.csv-derived case data, curation state, warnings,
              and provenance. Routine image QC remains in the Review Shell.
            </Typography>
          </Stack>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button component={RouterLink} to={reviewPath} variant="contained">
              Back to Case Review
            </Button>
            <Button component={RouterLink} to={`/datasets/${dsid}/cases`} variant="outlined">
              Worklist
            </Button>
          </Stack>
        </Stack>
      </Paper>

      {state.loading ? (
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minHeight: 160 }}>
          <CircularProgress size={28} />
          <Typography color="text.secondary">Loading case dossier...</Typography>
        </Stack>
      ) : null}

      {state.error ? <Alert severity="error">{state.error}</Alert> : null}

      {!state.loading && !state.error ? (
        <>
          <DossierSection title="Case Summary" testId="dossier-section-case-summary">
            <StatGrid
              items={[
                ['Case', caseId],
                ['Patient/source', caseSummary?.patient_id ?? selectedRow?.patient_id ?? '-'],
                ['Dataset', dsid],
                ['Group', caseSummary?.group ?? selectedRow?.group ?? '-'],
                ['QC status', formatStatus(caseSummary?.latest_curation_status ?? latestDecision?.status)],
                ['Warnings', String(warnings.length)],
                ['Queue state', queueItems.length > 0 ? `${queueItems.length} queued item(s)` : 'Not queued'],
              ]}
            />
          </DossierSection>

          <DossierSection title="Imaging Availability">
            <Stack spacing={1}>
              <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
                {(caseSummary?.available_phases ?? []).map((phase) => (
                  <Chip key={phase} label={phase} size="small" variant="outlined" />
                ))}
                <Chip label={`${caseSummary?.scan_count ?? sortedInventory.length} scans`} size="small" />
                <Chip label={`${caseSummary?.seg_count ?? 0} SEG`} size="small" />
                <Chip label={`${caseSummary?.voi_image_count ?? 0} VOI images`} size="small" />
                <Chip label={`${caseSummary?.voi_mask_count ?? 0} VOI masks`} size="small" />
              </Stack>
              <InventoryAvailabilityTable rows={sortedInventory} selectedRowId={selectedRowId} />
            </Stack>
          </DossierSection>

          <DossierSection title="Acquisition Metadata">
            <KeyValueCards
              groups={[
                ['Case core', state.dossier?.core ?? {}],
                ['Acquisition', state.dossier?.acquisition ?? {}],
              ]}
            />
          </DossierSection>

          <DossierSection title="Segmentation And VOI Metadata">
            <KeyValueCards
              groups={[
                ['Segmentation / VOI fields', state.dossier?.segmentation_voi ?? {}],
                ['Selected source paths', selectedRow ? selectedPathSummary(selectedRow) : {}],
              ]}
            />
          </DossierSection>

          <DossierSection title="Preprocessing / QC">
            <Stack spacing={1}>
              <KeyValueCards groups={[['Preprocessing / QC fields', state.dossier?.preprocessing_qc ?? {}]]} />
              {warnings.length === 0 ? (
                <Alert severity="success">No reconciliation warnings for this case.</Alert>
              ) : (
                warnings.map((warning, index) => (
                  <Alert key={`${warning.code}-${index}`} severity={warning.severity}>
                    {warning.row.canonical_phase}
                    {warning.row.scan_idx ? ` / scan ${warning.row.scan_idx}` : ''}: {warning.message}
                  </Alert>
                ))
              )}
            </Stack>
          </DossierSection>

          <DossierSection title="Curation History">
            <Stack spacing={0.85}>
              {state.history.length === 0 ? (
                <Alert severity="info">No prior curation decisions for this case.</Alert>
              ) : (
                [...state.history]
                  .sort((left, right) => right.reviewed_at.localeCompare(left.reviewed_at))
                  .map((decision) => (
                    <Paper key={decision.review_id} elevation={0} sx={{ p: 1.25 }}>
                      <Stack spacing={0.65}>
                        <Stack direction="row" spacing={0.65} flexWrap="wrap" useFlexGap>
                          <Chip
                            label={formatStatus(decision.status)}
                            color={statusChipColor(decision.status)}
                            size="small"
                          />
                          <Chip label={formatStatus(decision.target)} size="small" variant="outlined" />
                          <Chip label={formatStatus(decision.priority)} size="small" variant="outlined" />
                        </Stack>
                        <Typography variant="body2">{decision.comment || 'No comment.'}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {decision.reviewer || 'Unknown reviewer'} - {formatDate(decision.reviewed_at)}
                        </Typography>
                      </Stack>
                    </Paper>
                  ))
              )}
            </Stack>
          </DossierSection>

          <DossierSection title="Correction Queue State">
            <Stack spacing={1}>
              <Alert severity={queueItems.length > 0 ? 'warning' : 'info'}>
                {queueItems.length > 0
                  ? `${queueItems.length} correction queue item(s) exist for this case.`
                  : 'This case is not queued for correction.'}
              </Alert>
              <Button
                component="a"
                href={`/api/datasets/${dsid}/curation/correction-queue.csv`}
                target="_blank"
                rel="noreferrer"
                variant="outlined"
                sx={{ alignSelf: 'flex-start' }}
              >
                Export correction queue CSV
              </Button>
            </Stack>
          </DossierSection>

          <Accordion data-testid="advanced-raw-metadata">
            <AccordionSummary expandIcon={<span>+</span>}>
              <Typography>Advanced Raw Metadata</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={1.25}>
                <Typography variant="body2" color="text.secondary">
                  Raw database.csv fields, provenance fields, source-prefixed columns, and technical
                  paths are intentionally collapsed by default.
                </Typography>
                <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontSize: 12 }}>
                  {JSON.stringify(state.dossier?.advanced_raw_fields ?? [], null, 2)}
                </pre>
              </Stack>
            </AccordionDetails>
          </Accordion>
        </>
      ) : null}
    </Stack>
  )
}

function DossierSection({
  children,
  testId,
  title,
}: {
  children: ReactNode
  testId?: string
  title: string
}) {
  return (
    <Paper elevation={0} data-testid={testId} sx={{ p: { xs: 1.5, md: 2 } }}>
      <Stack spacing={1.25}>
        <Typography variant="h5">{title}</Typography>
        {children}
      </Stack>
    </Paper>
  )
}

function StatGrid({ items }: { items: Array<[string, string]> }) {
  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' },
        gap: 1,
      }}
    >
      {items.map(([label, value]) => (
        <Paper key={label} elevation={0} sx={{ p: 1.25, backgroundColor: 'rgba(255,255,255,0.02)' }}>
          <Typography variant="caption" color="text.secondary">
            {label}
          </Typography>
          <Typography variant="body1" fontWeight={700}>
            {value}
          </Typography>
        </Paper>
      ))}
    </Box>
  )
}

function InventoryAvailabilityTable({
  rows,
  selectedRowId,
}: {
  rows: CaseInventoryRow[]
  selectedRowId: string | null
}) {
  return (
    <TableContainer sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Phase</TableCell>
            <TableCell>Scan</TableCell>
            <TableCell>Side</TableCell>
            <TableCell>Complete</TableCell>
            <TableCell>SEG</TableCell>
            <TableCell>VOI image</TableCell>
            <TableCell>VOI mask</TableCell>
            <TableCell>Warnings</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.row_id} selected={row.row_id === selectedRowId}>
              <TableCell>{row.canonical_phase}</TableCell>
              <TableCell>{row.scan_idx || '-'}</TableCell>
              <TableCell>{row.side || '-'}</TableCell>
              <TableCell>{row.scope_availability.complete ? 'Available' : 'Missing'}</TableCell>
              <TableCell>{pathStatusLabel(row.seg_path.status)}</TableCell>
              <TableCell>{pathStatusLabel(row.voi_image_path.status)}</TableCell>
              <TableCell>{pathStatusLabel(row.voi_mask_path.status)}</TableCell>
              <TableCell>{row.qc_warnings.length}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

function KeyValueCards({ groups }: { groups: Array<[string, Record<string, unknown>]> }) {
  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' },
        gap: 1,
      }}
    >
      {groups.map(([title, fields]) => (
        <Paper key={title} elevation={0} sx={{ p: 1.25, backgroundColor: 'rgba(255,255,255,0.02)' }}>
          <Stack spacing={0.65}>
            <Typography variant="subtitle2">{title}</Typography>
            {Object.entries(fields).length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No fields available.
              </Typography>
            ) : (
              Object.entries(fields)
                .slice(0, 12)
                .map(([key, value]) => (
                  <Typography key={key} variant="body2">
                    <Typography component="span" variant="body2" color="text.secondary">
                      {key}:{' '}
                    </Typography>
                    {String(value ?? '-')}
                  </Typography>
                ))
            )}
          </Stack>
        </Paper>
      ))}
    </Box>
  )
}

function selectedPathSummary(row: CaseInventoryRow): Record<string, unknown> {
  return {
    nifti_status: row.nifti_path.status,
    seg_status: row.seg_path.status,
    voi_image_status: row.voi_image_path.status,
    voi_mask_status: row.voi_mask_path.status,
    side: row.side,
    raw_phase: row.raw_phase,
    canonical_phase: row.canonical_phase,
  }
}

function buildReviewQuery(rowId: string | null, scope: string | null): string {
  if (!rowId) {
    return ''
  }
  const params = new URLSearchParams({ row_id: rowId })
  if (scope === 'complete' || scope === 'voi') {
    params.set('scope', scope)
  }
  return `?${params.toString()}`
}

export default CaseDossierPage
