import {
  Autocomplete,
  Button,
  Chip,
  Stack,
  TextField,
  Typography,
  type FilterOptionsState,
} from '@mui/material'

import type { CaseSummary } from '../../services/api'
import { formatStatus, statusChipColor } from './reviewUi'

function filterCases(options: CaseSummary[], state: FilterOptionsState<CaseSummary>): CaseSummary[] {
  const input = state.inputValue.trim().toLowerCase()
  if (!input) return options
  return options.filter(
    (opt) =>
      opt.case_id.toLowerCase().includes(input) ||
      (opt.patient_id ?? '').toLowerCase().includes(input),
  )
}

interface CaseNavigatorProps {
  cases: CaseSummary[]
  currentCaseId: string
  error: string | null
  onSelect: (caseId: string) => void
  queuedCaseIds: string[]
}

function CaseNavigator({
  cases,
  currentCaseId,
  error,
  onSelect,
  queuedCaseIds,
}: CaseNavigatorProps) {
  const queued = new Set(queuedCaseIds)
  const currentIndex = cases.findIndex((entry) => entry.case_id === currentCaseId)
  const currentCase = currentIndex >= 0 ? cases[currentIndex] : null
  const previousCase = currentIndex > 0 ? cases[currentIndex - 1] : null
  const nextCase = currentIndex >= 0 ? cases[currentIndex + 1] ?? null : cases[0] ?? null

  return (
    <Stack spacing={0.85} data-testid="case-navigator">
      <Stack direction="row" spacing={0.75} alignItems="center" justifyContent="space-between">
        <Typography variant="overline" color="text.secondary">
          Case
        </Typography>
        <Chip
          label={currentIndex >= 0 ? `${currentIndex + 1}/${cases.length}` : `0/${cases.length}`}
          size="small"
          variant="outlined"
        />
      </Stack>

      <Autocomplete<CaseSummary, false, false, false>
        data-testid="case-autocomplete"
        filterOptions={filterCases}
        getOptionLabel={(opt) => opt.case_id}
        isOptionEqualToValue={(opt, val) => opt.case_id === val.case_id}
        ListboxProps={{ style: { maxHeight: 420 } }}
        onChange={(_, opt) => {
          if (opt) onSelect(opt.case_id)
        }}
        options={cases}
        renderInput={(params) => (
          <TextField
            {...params}
            data-testid="case-select"
            placeholder="Search case…"
            size="small"
          />
        )}
        renderOption={(props, opt) => {
          const idx = cases.findIndex((c) => c.case_id === opt.case_id)
          const isQueued = queued.has(opt.case_id)
          return (
            <li {...props} key={opt.case_id}>
              <Stack direction="row" spacing={0.75} alignItems="center" sx={{ width: '100%', minWidth: 0 }}>
                <Typography variant="body2" fontWeight={800} sx={{ flex: 1, minWidth: 0 }}>
                  {idx + 1}. {opt.case_id}
                </Typography>
                {isQueued ? <Chip label="Q" size="small" color="warning" /> : null}
                <Chip
                  label={opt.warning_count}
                  color={opt.warning_count > 0 ? 'warning' : statusChipColor(opt.latest_curation_status)}
                  size="small"
                  variant={opt.warning_count > 0 ? 'filled' : 'outlined'}
                />
              </Stack>
            </li>
          )
        }}
        size="small"
        value={currentCase}
      />

      {currentCase ? (
        <Stack direction="row" spacing={0.55} flexWrap="wrap" useFlexGap>
          <Chip label={currentCase.patient_id || 'No patient ID'} size="small" variant="outlined" />
          <Chip label={formatStatus(currentCase.latest_curation_status)} size="small" />
          <Chip
            label={`${currentCase.warning_count} warnings`}
            color={currentCase.warning_count > 0 ? 'warning' : 'default'}
            size="small"
            variant={currentCase.warning_count > 0 ? 'filled' : 'outlined'}
          />
        </Stack>
      ) : null}

      <Stack direction="row" spacing={0.75}>
        <Button
          size="small"
          variant="outlined"
          fullWidth
          disabled={!previousCase}
          onClick={() => previousCase && onSelect(previousCase.case_id)}
        >
          Previous
        </Button>
        <Button
          size="small"
          variant="contained"
          fullWidth
          disabled={!nextCase}
          onClick={() => nextCase && onSelect(nextCase.case_id)}
        >
          Next
        </Button>
      </Stack>

      {error ? (
        <Typography variant="caption" color="warning.main">
          {error}
        </Typography>
      ) : null}
    </Stack>
  )
}

export default CaseNavigator
