import {
  Box,
  Button,
  Chip,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import { useEffect, useMemo, useState } from 'react'

import type { CanonicalPhase, CaseInventoryRow, Scope } from '../../services/api'
import { PHASE_PRIORITY, pathStatusLabel, sortInventoryRows, sourceLabel } from './reviewUi'

interface SourceNavigatorProps {
  onSelectSource: (row: CaseInventoryRow, scope: Scope) => void
  rows: CaseInventoryRow[]
  scope: Scope
  selectedPhase: CanonicalPhase | null
  selectedRow: CaseInventoryRow | null
}

type SourceState = 'selected' | 'available' | 'warning' | 'missing' | 'disabled'

interface ScanGroup {
  key: string
  phase: CanonicalPhase
  scanIdx: string
  rows: CaseInventoryRow[]
}

const PRIMARY_PHASES: CanonicalPhase[] = ['NP', 'CMP', 'NC', 'EXC']

function SourceNavigator({
  onSelectSource,
  rows,
  scope,
  selectedPhase,
  selectedRow,
}: SourceNavigatorProps) {
  const sortedRows = useMemo(() => sortInventoryRows(rows), [rows])
  const phaseOptions = useMemo(() => buildPhaseOptions(sortedRows), [sortedRows])
  const phasePresence = useMemo(
    () => new Set(sortedRows.map((row) => row.canonical_phase)),
    [sortedRows],
  )
  const [phaseFilter, setPhaseFilter] = useState<CanonicalPhase | null>(
    firstAvailablePhase(phaseOptions, phasePresence, selectedRow?.canonical_phase ?? selectedPhase),
  )

  useEffect(() => {
    const nextPhase = firstAvailablePhase(
      phaseOptions,
      phasePresence,
      selectedRow?.canonical_phase ?? selectedPhase,
    )
    if (nextPhase) {
      setPhaseFilter(nextPhase)
    }
  }, [phaseOptions, phasePresence, selectedPhase, selectedRow?.canonical_phase])

  const activePhase =
    phaseFilter && phasePresence.has(phaseFilter)
      ? phaseFilter
      : firstAvailablePhase(phaseOptions, phasePresence)
  const phaseRows = activePhase
    ? sortedRows.filter((row) => row.canonical_phase === activePhase)
    : sortedRows
  const scanGroups = buildScanGroups(phaseRows)
  const voiSides = buildVoiSides(sortedRows)

  return (
    <Stack spacing={1.15} data-testid="source-navigator">
      <Typography variant="overline" color="text.secondary">
        Source Navigator
      </Typography>

      <Typography variant="overline" color="text.secondary">
        Phase selector
      </Typography>

      <Stack direction="row" spacing={0.65} flexWrap="wrap" useFlexGap>
        {phaseOptions.map((phase) => {
          const selected = phase === activePhase
          const available = phasePresence.has(phase)
          return (
            <Button
              key={phase}
              data-testid="phase-filter-chip"
              aria-pressed={selected}
              disabled={!available}
              size="small"
              variant={selected ? 'contained' : 'outlined'}
              onClick={() => setPhaseFilter(phase)}
              sx={{
                minHeight: 30,
                minWidth: 48,
                borderRadius: 999,
                px: 1.1,
                py: 0.2,
                fontWeight: 800,
                opacity: available ? 1 : 0.5,
              }}
            >
              {phase}
            </Button>
          )
        })}
      </Stack>

      <Stack spacing={0.65}>
        <Typography variant="caption" color="text.secondary">
          Viewing
        </Typography>
        <Chip
          label={sourceLabel(selectedRow, scope)}
          color={scope === 'voi' ? 'success' : 'primary'}
          variant="outlined"
          size="small"
          sx={{ justifyContent: 'flex-start', maxWidth: '100%' }}
        />
      </Stack>

      <Stack spacing={0.8}>
        {scanGroups.map((group) => (
          <ScanSourceGroup
            key={group.key}
            group={group}
            onSelectSource={onSelectSource}
            scope={scope}
            selectedRow={selectedRow}
            voiSides={voiSides}
          />
        ))}
        {scanGroups.length === 0 ? (
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
              No sources are available for this phase.
            </Typography>
          </Box>
        ) : null}
      </Stack>
    </Stack>
  )
}

function ScanSourceGroup({
  group,
  onSelectSource,
  scope,
  selectedRow,
  voiSides,
}: {
  group: ScanGroup
  onSelectSource: (row: CaseInventoryRow, scope: Scope) => void
  scope: Scope
  selectedRow: CaseInventoryRow | null
  voiSides: string[]
}) {
  const completeRow = group.rows.find((row) => row.scope_availability.complete) ?? group.rows[0] ?? null

  return (
    <Box
      data-testid="source-scan-group"
      sx={{
        border: '1px solid',
        borderColor: 'rgba(255,255,255,0.16)',
        borderRadius: 1,
        backgroundColor: 'rgba(255,255,255,0.025)',
        px: 0.8,
        py: 0.75,
      }}
    >
      <Stack spacing={0.65}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
          <Typography variant="caption" sx={{ color: 'rgba(226,232,240,0.88)', fontWeight: 800 }}>
            Scan {group.scanIdx || '-'}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {group.phase}
          </Typography>
        </Stack>

        <Stack direction="row" spacing={0.55} flexWrap="wrap" useFlexGap>
          <SourceChip
            ariaLabel={`${group.phase} · scan ${group.scanIdx || '-'} · Complete CT`}
            label="CT"
            detail={completeDetail(completeRow)}
            row={completeRow}
            scope="complete"
            selected={Boolean(
              selectedRow &&
                completeRow &&
                selectedRow.row_id === completeRow.row_id &&
                scope === 'complete',
            )}
            state={completeState(completeRow, selectedRow, scope)}
            onSelectSource={onSelectSource}
          />
          {voiSides.map((side) => {
            const row = group.rows.find((candidate) => (candidate.side ?? '').toUpperCase() === side)
            return (
              <SourceChip
                ariaLabel={`${group.phase} · scan ${group.scanIdx || '-'} · ${side ? `VOI ${side}` : 'VOI'}`}
                key={side || 'voi'}
                label={side ? `VOI ${side}` : 'VOI'}
                detail={voiDetail(row ?? null)}
                row={row ?? null}
                scope="voi"
                selected={Boolean(
                  selectedRow &&
                    row &&
                    selectedRow.row_id === row.row_id &&
                    scope === 'voi',
                )}
                state={voiState(row ?? null, selectedRow, scope)}
                onSelectSource={onSelectSource}
              />
            )
          })}
        </Stack>
      </Stack>
    </Box>
  )
}

function SourceChip({
  ariaLabel,
  detail,
  label,
  onSelectSource,
  row,
  scope,
  selected,
  state,
}: {
  ariaLabel: string
  detail: string
  label: string
  onSelectSource: (row: CaseInventoryRow, scope: Scope) => void
  row: CaseInventoryRow | null
  scope: Scope
  selected: boolean
  state: SourceState
}) {
  const disabled = !row || state === 'missing' || state === 'disabled'
  const color =
    selected ? 'primary' : state === 'warning' ? 'warning' : state === 'available' ? 'success' : 'inherit'

  return (
    <Tooltip title={detail}>
      <span>
        <Button
          data-testid="source-card"
          data-source-state={selected ? 'selected' : state}
          aria-label={row ? sourceLabel(row, scope) : ariaLabel}
          disabled={disabled}
          onClick={() => {
            if (row) {
              onSelectSource(row, scope)
            }
          }}
          size="small"
          variant={selected ? 'contained' : 'outlined'}
          color={color === 'inherit' ? undefined : color}
          sx={{
            minHeight: 34,
            px: 1,
            py: 0.35,
            borderRadius: 1,
            textTransform: 'none',
            fontWeight: 800,
            opacity: disabled ? 0.55 : 1,
          }}
        >
          <Stack direction="row" spacing={0.55} alignItems="center">
            <span>{label}</span>
            {state === 'warning' ? <Chip label="!" size="small" color="warning" sx={{ height: 18 }} /> : null}
            {state === 'missing' ? <Chip label="Missing" size="small" sx={{ height: 18 }} /> : null}
          </Stack>
        </Button>
      </span>
    </Tooltip>
  )
}

function buildPhaseOptions(rows: CaseInventoryRow[]): CanonicalPhase[] {
  const present = new Set(rows.map((row) => row.canonical_phase))
  const ordered = [...PRIMARY_PHASES]
  const additional = PHASE_PRIORITY.filter((phase) => present.has(phase) && !ordered.includes(phase))
  return [...ordered, ...additional]
}

function firstAvailablePhase(
  phaseOptions: CanonicalPhase[],
  phasePresence: Set<CanonicalPhase>,
  preferred?: CanonicalPhase | null,
): CanonicalPhase | null {
  if (preferred && phasePresence.has(preferred)) {
    return preferred
  }
  return phaseOptions.find((phase) => phasePresence.has(phase)) ?? null
}

function buildScanGroups(rows: CaseInventoryRow[]): ScanGroup[] {
  const groups = new Map<string, ScanGroup>()
  for (const row of rows) {
    const scanIdx = row.scan_idx ?? ''
    const key = `${row.canonical_phase}:${scanIdx}`
    const group = groups.get(key)
    if (group) {
      group.rows.push(row)
    } else {
      groups.set(key, {
        key,
        phase: row.canonical_phase,
        scanIdx,
        rows: [row],
      })
    }
  }
  return Array.from(groups.values())
}

function buildVoiSides(rows: CaseInventoryRow[]): string[] {
  const sides = Array.from(
    new Set(
      rows
        .map((row) => (row.side ?? '').toUpperCase())
        .filter((side) => side.length > 0),
    ),
  ).sort()
  if (sides.length > 0) {
    return sides
  }
  if (rows.some((row) => row.scope_availability.voi || row.has_voi_image || row.has_voi_mask)) {
    return ['']
  }
  return ['L', 'R']
}

function completeState(
  row: CaseInventoryRow | null,
  selectedRow: CaseInventoryRow | null,
  scope: Scope,
): SourceState {
  if (!row) {
    return 'disabled'
  }
  if (selectedRow?.row_id === row.row_id && scope === 'complete') {
    return 'selected'
  }
  if (!row.scope_availability.complete || row.nifti_path.status !== 'exists') {
    return 'missing'
  }
  return completeHasWarning(row) ? 'warning' : 'available'
}

function voiState(
  row: CaseInventoryRow | null,
  selectedRow: CaseInventoryRow | null,
  scope: Scope,
): SourceState {
  if (!row) {
    return 'missing'
  }
  if (selectedRow?.row_id === row.row_id && scope === 'voi') {
    return 'selected'
  }
  if (!row.scope_availability.voi || row.voi_image_path.status !== 'exists') {
    return 'missing'
  }
  return voiHasWarning(row) ? 'warning' : 'available'
}

function completeHasWarning(row: CaseInventoryRow): boolean {
  return row.seg_path.status !== 'exists' || row.qc_warnings.some((warning) => warning.scope === 'complete')
}

function voiHasWarning(row: CaseInventoryRow): boolean {
  return (
    row.voi_mask_path.status !== 'exists' ||
    row.qc_warnings.some((warning) => warning.scope === 'voi')
  )
}

function completeDetail(row: CaseInventoryRow | null): string {
  if (!row) {
    return 'Complete CT is not available for this scan.'
  }
  if (!row.scope_availability.complete || row.nifti_path.status !== 'exists') {
    return 'Complete CT is missing.'
  }
  return `Complete CT. SEG ${pathStatusLabel(row.seg_path.status)}.`
}

function voiDetail(row: CaseInventoryRow | null): string {
  if (!row) {
    return 'VOI source is not available for this scan.'
  }
  if (!row.scope_availability.voi || row.voi_image_path.status !== 'exists') {
    return `VOI image ${pathStatusLabel(row.voi_image_path.status)}.`
  }
  return `VOI image ${pathStatusLabel(row.voi_image_path.status)}. VOI mask ${pathStatusLabel(row.voi_mask_path.status)}.`
}

export default SourceNavigator
