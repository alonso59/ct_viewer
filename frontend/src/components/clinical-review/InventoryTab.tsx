import {
  Box,
  Button,
  Chip,
  IconButton,
  Stack,
  SvgIcon,
  Tooltip,
  Typography,
} from '@mui/material'

import type { CanonicalPhase, CaseInventoryRow, Scope } from '../../services/api'
import { formatStatus, pathStatusLabel, sortInventoryRows, sourceLabel, statusChipColor } from './reviewUi'

function EditOutlinedIcon(props: React.ComponentProps<typeof SvgIcon>) {
  return (
    <SvgIcon {...props} viewBox="0 0 24 24">
      <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z" />
    </SvgIcon>
  )
}

interface InventoryTabProps {
  onSelectSource: (row: CaseInventoryRow, scope: Scope) => void
  onPhaseCorrection?: (scanIdx: string | null) => void
  rows: CaseInventoryRow[]
  scope: Scope
  selectedRowId: string | null
}

/** Group key that identifies a single scan (phase × scan_idx). */
type ScanGroupKey = string
interface ScanGroup {
  key: ScanGroupKey
  phase: CanonicalPhase
  scanIdx: string | null
  rows: CaseInventoryRow[]
}

function buildScanGroups(sortedRows: CaseInventoryRow[]): ScanGroup[] {
  const map = new Map<ScanGroupKey, ScanGroup>()
  for (const row of sortedRows) {
    const k: ScanGroupKey = `${row.canonical_phase}_${row.scan_idx ?? ''}`
    const group = map.get(k)
    if (group) {
      group.rows.push(row)
    } else {
      map.set(k, {
        key: k,
        phase: row.canonical_phase,
        scanIdx: row.scan_idx ?? null,
        rows: [row],
      })
    }
  }
  return Array.from(map.values())
}

function InventoryTab({ onSelectSource, onPhaseCorrection, rows, scope, selectedRowId }: InventoryTabProps) {
  const sortedRows = sortInventoryRows(rows)
  const scanGroups = buildScanGroups(sortedRows)

  return (
    <Stack spacing={0.75} data-testid="inventory-detail-list">
      {scanGroups.map((group) => (
        <Box
          key={group.key}
          data-testid="inventory-scan-group"
          sx={{
            border: '1px solid',
            borderColor: 'rgba(255,255,255,0.12)',
            borderRadius: 1,
            backgroundColor: 'rgba(0,0,0,0.18)',
            px: 0.85,
            py: 0.75,
          }}
        >
          <Stack spacing={0.65}>
            <Stack direction="row" spacing={0.75} alignItems="center" justifyContent="space-between">
              <Stack direction="row" spacing={0.55} alignItems="center" sx={{ minWidth: 0 }}>
                <Chip label={group.phase} color="default" size="small" variant="outlined" />
                <Typography variant="body2" fontWeight={800} noWrap>
                  Scan {group.scanIdx || '-'}
                </Typography>
                {onPhaseCorrection ? (
                  <Tooltip title={`Change phase for scan ${group.scanIdx ?? '-'}`}>
                    <IconButton
                      size="small"
                      onClick={() => onPhaseCorrection(group.scanIdx)}
                      sx={{ opacity: 0.68, '&:hover': { opacity: 1 } }}
                    >
                      <EditOutlinedIcon sx={{ fontSize: 14 }} />
                    </IconButton>
                  </Tooltip>
                ) : null}
              </Stack>
              <Chip label={`${group.rows.length} row${group.rows.length === 1 ? '' : 's'}`} size="small" />
            </Stack>

            <Stack spacing={0.55}>
              {group.rows.map((row) => (
                <InventorySourceRow
                  key={row.row_id}
                  onSelectSource={onSelectSource}
                  row={row}
                  scope={scope}
                  selected={row.row_id === selectedRowId}
                />
              ))}
            </Stack>
          </Stack>
        </Box>
      ))}
      {sortedRows.length === 0 ? (
        <Box
          sx={{
            border: '1px dashed',
            borderColor: 'divider',
            borderRadius: 1,
            px: 1,
            py: 1.1,
          }}
        >
          <Typography variant="body2" color="text.secondary">
            No inventory rows are available for this case.
          </Typography>
        </Box>
      ) : null}
    </Stack>
  )
}

function InventorySourceRow({
  onSelectSource,
  row,
  scope,
  selected,
}: {
  onSelectSource: (row: CaseInventoryRow, scope: Scope) => void
  row: CaseInventoryRow
  scope: Scope
  selected: boolean
}) {
  const nextScope: Scope =
    scope === 'voi' && row.scope_availability.voi
      ? 'voi'
      : row.scope_availability.complete
        ? 'complete'
        : 'voi'
  const available = isSourceAvailable(row, nextScope)
  const warningCount = row.qc_warnings.length

  return (
    <Button
      data-testid="inventory-row"
      data-selected={selected ? 'true' : 'false'}
      disabled={!available}
      fullWidth
      onClick={() => onSelectSource(row, nextScope)}
      variant={selected ? 'contained' : 'outlined'}
      color={selected ? 'primary' : nextScope === 'voi' ? 'success' : 'inherit'}
      sx={{
        alignItems: 'stretch',
        justifyContent: 'flex-start',
        minHeight: 54,
        px: 0.85,
        py: 0.7,
        borderRadius: 1,
        textTransform: 'none',
        opacity: available ? 1 : 0.58,
      }}
    >
      <Stack spacing={0.55} sx={{ minWidth: 0, width: '100%' }}>
        <Stack direction="row" spacing={0.55} alignItems="center" justifyContent="space-between">
          <Typography variant="body2" fontWeight={900} noWrap>
            {sourceLabel(row, nextScope)}
          </Typography>
          {selected ? <Chip label="Displayed" color="primary" size="small" /> : null}
        </Stack>

        <Stack direction="row" spacing={0.45} flexWrap="wrap" useFlexGap>
          <AvailabilityChip label="SEG" available={row.seg_path.status === 'exists'} status={row.seg_path.status} />
          <AvailabilityChip
            label="VOI image"
            available={row.voi_image_path.status === 'exists'}
            status={row.voi_image_path.status}
          />
          <AvailabilityChip
            label="VOI mask"
            available={row.voi_mask_path.status === 'exists'}
            status={row.voi_mask_path.status}
          />
          <Chip
            label={formatStatus(row.latest_curation_status)}
            color={statusChipColor(row.latest_curation_status)}
            size="small"
            variant={row.latest_curation_status ? 'filled' : 'outlined'}
          />
          <Chip
            label={`${warningCount} warning${warningCount === 1 ? '' : 's'}`}
            color={warningCount > 0 ? 'warning' : 'default'}
            size="small"
            variant={warningCount > 0 ? 'filled' : 'outlined'}
          />
        </Stack>
      </Stack>
    </Button>
  )
}

function isSourceAvailable(row: CaseInventoryRow, scope: Scope): boolean {
  if (scope === 'complete') {
    return row.scope_availability.complete && row.nifti_path.status === 'exists'
  }
  return row.scope_availability.voi && row.voi_image_path.status === 'exists'
}

function AvailabilityChip({
  available,
  label,
  status,
}: {
  available: boolean
  label: string
  status: string | null | undefined
}) {
  return (
    <Chip
      label={`${label} ${available ? 'OK' : pathStatusLabel(status)}`}
      color={available ? 'success' : 'default'}
      size="small"
      variant={available ? 'filled' : 'outlined'}
    />
  )
}

export default InventoryTab
