import { Alert, Chip, Stack, Typography } from '@mui/material'

import type { CaseInventoryRow } from '../../services/api'

interface WarningsTabProps {
  rows: CaseInventoryRow[]
  selectedRow: CaseInventoryRow | null
}

function WarningsTab({ rows, selectedRow }: WarningsTabProps) {
  const selectedWarnings = selectedRow?.qc_warnings ?? []
  const otherWarnings = rows
    .filter((row) => row.row_id !== selectedRow?.row_id)
    .flatMap((row) =>
      row.qc_warnings.map((warning) => ({
        ...warning,
        row,
      })),
    )
  const selectedLabel = selectedRow
    ? [
        selectedRow.canonical_phase,
        selectedRow.scan_idx ? `scan ${selectedRow.scan_idx}` : null,
        selectedRow.side ? `side ${selectedRow.side}` : null,
      ]
        .filter(Boolean)
        .join(' / ')
    : 'selected source'

  if (selectedWarnings.length === 0 && otherWarnings.length === 0) {
    return <Alert severity="success">No warnings for this case.</Alert>
  }

  return (
    <Stack spacing={1} data-testid="warnings-tab-panel">
      <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
        <Typography variant="subtitle2">Warnings</Typography>
        <Chip label={`${selectedWarnings.length} selected source`} size="small" />
        <Chip label={`${otherWarnings.length} other case`} size="small" variant="outlined" />
      </Stack>

      {selectedWarnings.length > 0 ? (
        <Stack spacing={0.75}>
          <Typography variant="caption" color="text.secondary">
            {selectedLabel}
          </Typography>
          {selectedWarnings.map((warning, index) => (
            <Alert key={`selected-${warning.code}-${index}`} severity={warning.severity}>
              {warning.message}
            </Alert>
          ))}
        </Stack>
      ) : (
        <Alert severity="success">No warnings for the selected source.</Alert>
      )}

      {otherWarnings.length > 0 ? (
        <Stack spacing={0.75}>
          <Typography variant="caption" color="text.secondary">
            Other case warnings
          </Typography>
          {otherWarnings.map((warning, index) => (
            <Alert key={`other-${warning.code}-${index}`} severity={warning.severity}>
              {warning.row.canonical_phase}
              {warning.row.scan_idx ? ` / scan ${warning.row.scan_idx}` : ''}: {warning.message}
            </Alert>
          ))}
        </Stack>
      ) : null}
    </Stack>
  )
}

export default WarningsTab
