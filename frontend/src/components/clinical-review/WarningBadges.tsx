import { Chip, Stack, Typography } from '@mui/material'

import type { CaseInventoryRow } from '../../services/api'
import { isMissingSegWarning } from './reviewUi'

interface WarningBadgesProps {
  rows: CaseInventoryRow[]
  selectedRow: CaseInventoryRow | null
}

function WarningBadges({ rows, selectedRow }: WarningBadgesProps) {
  const warnings = rows.flatMap((row) =>
    row.qc_warnings.map((warning) => ({
      ...warning,
      row,
    })),
  )
  const selectedWarnings = selectedRow?.qc_warnings ?? []
  const missingSegActive = Boolean(
    selectedRow &&
      (selectedRow.seg_path.status !== 'exists' ||
        selectedWarnings.some((warning) => isMissingSegWarning(warning.code))),
  )

  return (
    <Stack spacing={0.75} data-testid="warning-badges">
      <Stack direction="row" spacing={0.6} alignItems="center" justifyContent="space-between">
        <Typography variant="overline" color="text.secondary">
          Warnings
        </Typography>
        <Chip label={warnings.length} color={warnings.length > 0 ? 'warning' : 'default'} size="small" />
      </Stack>
      <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
        {missingSegActive ? <Chip label="Missing SEG blocks QC" color="error" size="small" /> : null}
        {warnings
          .filter((warning) => !isMissingSegWarning(warning.code))
          .slice(0, 5)
          .map((warning, index) => (
            <Chip
              key={`${warning.code}-${warning.row.row_id}-${index}`}
              label={warningLabel(warning.code)}
              color="warning"
              size="small"
              variant="outlined"
            />
          ))}
        {warnings.length === 0 ? <Chip label="No active warnings" color="success" size="small" variant="outlined" /> : null}
      </Stack>
      {warnings.length > 0 ? (
        <Typography variant="caption" color="text.secondary">
          Non-Missing-SEG warnings are informational in v2.0.
        </Typography>
      ) : null}
    </Stack>
  )
}

function warningLabel(code: string): string {
  const normalized = code.toLowerCase()
  if (normalized.includes('missing_voi')) {
    return 'Missing VOI'
  }
  if (normalized.includes('wrong_phase')) {
    return 'Wrong phase suspected'
  }
  if (normalized.includes('wrong_side') || normalized.includes('laterality')) {
    return 'Wrong side suspected'
  }
  if (normalized.includes('duplicate')) {
    return 'Duplicate scan'
  }
  if (normalized.includes('ambiguous')) {
    return 'Ambiguous phase'
  }
  return code.replaceAll('_', ' ')
}

export default WarningBadges
