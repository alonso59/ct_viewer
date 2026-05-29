import { useDeferredValue, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { useNavigate, useParams } from 'react-router-dom'

import {
  apiClient,
  getApiErrorMessage,
  type CanonicalPhase,
  type CaseSummary,
  type DatabaseValidationReport,
} from '../services/api'
import CorrectionQueueButton from '../components/curation/CorrectionQueueButton'

function CaseWorklistPage() {
  const { dsid = 'unknown-dataset' } = useParams<{ dsid: string }>()
  const navigate = useNavigate()
  const [requestState, setRequestState] = useState<{
    datasetId: string | null
    cases: CaseSummary[]
    error: string | null
  }>({
    datasetId: null,
    cases: [],
    error: null,
  })
  const [validationState, setValidationState] = useState<{
    datasetId: string | null
    report: DatabaseValidationReport | null
    error: string | null
  }>({
    datasetId: null,
    report: null,
    error: null,
  })
  const [search, setSearch] = useState('')
  const [groupFilter, setGroupFilter] = useState('all')
  const [phaseFilter, setPhaseFilter] = useState<CanonicalPhase | 'all'>('all')
  const deferredSearch = useDeferredValue(search)
  const loading = requestState.datasetId !== dsid
  const cases = useMemo(
    () => (requestState.datasetId === dsid ? requestState.cases : []),
    [dsid, requestState.cases, requestState.datasetId],
  )
  const error = requestState.datasetId === dsid ? requestState.error : null
  const validationReport =
    validationState.datasetId === dsid ? validationState.report : null
  const validationError = validationState.datasetId === dsid ? validationState.error : null

  useEffect(() => {
    let active = true
    apiClient
      .listCases(dsid)
      .then((response) => {
        if (!active) {
          return
        }
        setRequestState({
          datasetId: dsid,
          cases: response,
          error: null,
        })
      })
      .catch((requestError) => {
        if (!active) {
          return
        }
        setRequestState({
          datasetId: dsid,
          cases: [],
          error: getApiErrorMessage(requestError),
        })
      })
    return () => {
      active = false
    }
  }, [dsid])

  useEffect(() => {
    let active = true
    setValidationState({ datasetId: null, report: null, error: null })
    apiClient
      .getDatabaseValidation(dsid)
      .then((response) => {
        if (!active) {
          return
        }
        setValidationState({ datasetId: dsid, report: response, error: null })
      })
      .catch((requestError) => {
        if (!active) {
          return
        }
        setValidationState({
          datasetId: dsid,
          report: null,
          error: getApiErrorMessage(requestError),
        })
      })
    return () => {
      active = false
    }
  }, [dsid])

  const groupOptions = useMemo(
    () =>
      Array.from(new Set(cases.map((entry) => entry.group ?? 'Unknown'))).sort((left, right) =>
        left.localeCompare(right, undefined, { sensitivity: 'base' }),
      ),
    [cases],
  )
  const phaseOptions = useMemo(
    () =>
      Array.from(new Set(cases.flatMap((entry) => entry.available_phases))).sort(
        phaseSort,
      ),
    [cases],
  )

  const normalizedSearch = deferredSearch.trim().toLowerCase()
  const filteredCases = cases
    .filter((entry) => {
      if (
        normalizedSearch &&
        !`${entry.case_id} ${entry.patient_id ?? ''}`.toLowerCase().includes(normalizedSearch)
      ) {
        return false
      }
      if (groupFilter !== 'all' && (entry.group ?? 'Unknown') !== groupFilter) {
        return false
      }
      if (phaseFilter !== 'all' && !entry.available_phases.includes(phaseFilter)) {
        return false
      }
      return true
    })
    .sort((left, right) =>
      left.case_id.localeCompare(right.case_id, undefined, {
        sensitivity: 'base',
        numeric: true,
      }),
    )
  const warningCaseCount = cases.filter((entry) => entry.warning_count > 0).length
  const reviewedCaseCount = cases.filter((entry) => entry.latest_curation_status).length

  return (
    <Paper
      elevation={0}
      sx={{
        minHeight: 420,
        px: { xs: 2, md: 3 },
        py: { xs: 2, md: 3 },
      }}
    >
      <Stack spacing={2.5}>
        <Box>
          <Typography variant="overline" color="text.secondary">
            Medical Curation Worklist
          </Typography>
          <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap">
            <Typography variant="h3">Cases</Typography>
            <Chip label={dsid} color="primary" variant="outlined" />
            <CorrectionQueueButton datasetId={dsid} />
          </Stack>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
            <Chip label={`${cases.length} cases`} size="small" variant="outlined" />
            <Chip
              label={`${reviewedCaseCount} reviewed`}
              color={reviewedCaseCount > 0 ? 'success' : 'default'}
              size="small"
              variant="outlined"
            />
            <Chip
              label={`${warningCaseCount} with warnings`}
              color={warningCaseCount > 0 ? 'warning' : 'default'}
              size="small"
              variant={warningCaseCount > 0 ? 'filled' : 'outlined'}
            />
          </Stack>
        </Box>

        <DatasetValidationBanner
          error={validationError}
          loading={validationState.datasetId !== dsid}
          report={validationReport}
        />

        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
          <TextField
            label="Search case or patient"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            fullWidth
          />
          <FormControl sx={{ minWidth: { xs: '100%', md: 180 } }}>
            <InputLabel id="case-group-filter-label">Group</InputLabel>
            <Select
              labelId="case-group-filter-label"
              label="Group"
              value={groupFilter}
              onChange={(event) => setGroupFilter(event.target.value)}
            >
              <MenuItem value="all">All groups</MenuItem>
              {groupOptions.map((group) => (
                <MenuItem key={group} value={group}>
                  {group}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl sx={{ minWidth: { xs: '100%', md: 180 } }}>
            <InputLabel id="case-phase-filter-label">Phase</InputLabel>
            <Select
              labelId="case-phase-filter-label"
              label="Phase"
              value={phaseFilter}
              onChange={(event) => setPhaseFilter(event.target.value as CanonicalPhase | 'all')}
            >
              <MenuItem value="all">All phases</MenuItem>
              {phaseOptions.map((phase) => (
                <MenuItem key={phase} value={phase}>
                  {phase}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Stack>

        {loading ? (
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minHeight: 180 }}>
            <CircularProgress size={28} />
            <Typography color="text.secondary">Loading case worklist...</Typography>
          </Stack>
        ) : null}

        {!loading && error ? <Alert severity="error">{error}</Alert> : null}

        {!loading && !error ? (
          <TableContainer
            sx={{
              border: '1px solid',
              borderColor: 'divider',
              borderRadius: 1,
              backgroundColor: 'rgba(255, 255, 255, 0.02)',
            }}
          >
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Case</TableCell>
                  <TableCell>Patient</TableCell>
                  <TableCell>Group</TableCell>
                  <TableCell>Phases</TableCell>
                  <TableCell align="right">Scans</TableCell>
                  <TableCell>VOI</TableCell>
                  <TableCell>QC</TableCell>
                  <TableCell align="right">Warnings</TableCell>
                  <TableCell>Comment</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filteredCases.map((entry) => (
                  <TableRow
                    hover
                    key={entry.case_id}
                    data-testid="case-worklist-row"
                    onClick={() => navigate(`/datasets/${dsid}/cases/${entry.case_id}/review`)}
                    sx={{
                      cursor: 'pointer',
                      '&:last-child td': { borderBottom: 0 },
                    }}
                  >
                    <TableCell>
                      <Typography fontWeight={700}>{entry.case_id}</Typography>
                    </TableCell>
                    <TableCell>{entry.patient_id ?? 'Unknown'}</TableCell>
                    <TableCell>{entry.group ?? 'Unknown'}</TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
                        {entry.available_phases.map((phase) => (
                          <Chip key={phase} label={phase} size="small" variant="outlined" />
                        ))}
                      </Stack>
                    </TableCell>
                    <TableCell align="right">{entry.scan_count}</TableCell>
                    <TableCell>
                      {entry.voi_sides.length > 0
                        ? entry.voi_sides.join(' / ')
                        : `${entry.voi_image_count} image`}
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={formatStatus(entry.latest_curation_status)}
                        color={statusChipColor(entry.latest_curation_status)}
                        size="small"
                        variant={entry.latest_curation_status ? 'filled' : 'outlined'}
                      />
                    </TableCell>
                    <TableCell align="right">
                      <Chip
                        label={entry.warning_count}
                        color={entry.warning_count > 0 ? 'warning' : 'default'}
                        size="small"
                        variant={entry.warning_count > 0 ? 'filled' : 'outlined'}
                      />
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={entry.has_comments ? 'Comment' : 'None'}
                        size="small"
                        variant={entry.has_comments ? 'filled' : 'outlined'}
                        color={entry.has_comments ? 'primary' : 'default'}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        ) : null}

        {!loading && !error && filteredCases.length === 0 ? (
          <Alert severity="info">No cases match the current filters.</Alert>
        ) : null}
      </Stack>
    </Paper>
  )
}

function phaseSort(left: CanonicalPhase, right: CanonicalPhase): number {
  const order: CanonicalPhase[] = ['NP', 'CMP', 'NC', 'DELAY', 'UNK']
  return order.indexOf(left) - order.indexOf(right)
}

function formatStatus(status: string | null): string {
  if (!status) {
    return 'Not reviewed'
  }
  return status.replaceAll('_', ' ')
}

function statusChipColor(
  status: string | null,
): 'default' | 'primary' | 'success' | 'warning' | 'error' {
  if (!status || status === 'not_reviewed') {
    return 'default'
  }
  if (status === 'accepted') {
    return 'success'
  }
  if (status === 'rejected' || status === 'missing') {
    return 'error'
  }
  if (
    status.includes('correction') ||
    status.includes('wrong_') ||
    status === 'cannot_assess'
  ) {
    return 'warning'
  }
  return 'primary'
}

function DatasetValidationBanner({
  error,
  loading,
  report,
}: {
  error: string | null
  loading: boolean
  report: DatabaseValidationReport | null
}) {
  if (loading) {
    return (
      <Alert severity="info" data-testid="dataset-validation-banner">
        Checking database.csv validation...
      </Alert>
    )
  }

  if (error) {
    return (
      <Alert severity="warning" data-testid="dataset-validation-banner">
        Dataset validation is unavailable: {error}
      </Alert>
    )
  }

  if (!report) {
    return null
  }

  const requiredTotal = report.required_columns.length
  const requiredPresent = report.required_columns.filter((column) => column.present).length
  const pathWarningCount = report.warnings.filter(
    (warning) =>
      Boolean(warning.path_field) ||
      warning.code.includes('missing') ||
      warning.code.includes('unreadable'),
  ).length
  const ready =
    report.has_database &&
    requiredPresent === requiredTotal &&
    !report.warnings.some((warning) => warning.severity === 'error')

  return (
    <Paper
      elevation={0}
      data-testid="dataset-validation-banner"
      sx={{
        border: '1px solid',
        borderColor: ready ? 'success.main' : 'warning.main',
        p: 1.5,
      }}
    >
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Chip
          label={ready ? 'Ready for review' : 'Needs attention'}
          color={ready ? 'success' : 'warning'}
          size="small"
        />
        <Chip
          label={`database.csv: ${report.has_database ? 'Present' : 'Missing'}`}
          color={report.has_database ? 'success' : 'warning'}
          size="small"
          variant="outlined"
        />
        <Chip label={`Rows: ${report.row_count}`} size="small" variant="outlined" />
        <Chip label={`Cases: ${report.case_count}`} size="small" variant="outlined" />
        <Chip
          label={`Required columns: ${requiredPresent}/${requiredTotal}`}
          color={requiredPresent === requiredTotal ? 'success' : 'warning'}
          size="small"
          variant="outlined"
        />
        <Chip
          label={`Paths: ${pathWarningCount === 0 ? 'OK' : 'Needs attention'}`}
          color={pathWarningCount === 0 ? 'success' : 'warning'}
          size="small"
          variant="outlined"
        />
        <Chip
          label={`Warnings: ${report.warnings.length}`}
          color={report.warnings.length === 0 ? 'default' : 'warning'}
          size="small"
          variant={report.warnings.length === 0 ? 'outlined' : 'filled'}
        />
      </Stack>
    </Paper>
  )
}

export default CaseWorklistPage
