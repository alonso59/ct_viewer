import type {
  Axis,
  CanonicalPhase,
  CaseInventoryRow,
  CurationDecision,
  CurationStatus,
  Scope,
} from '../../services/api'

export const PANEL_ACCENTS: Record<Axis, string> = {
  axial: '#fbbf24',
  coronal: '#ef4444',
  sagittal: '#22c55e',
}

export const LAYER_META: Record<number, { label: string; color: string; defaultOpacity: number }> = {
  1: { label: 'Kidney', color: '#7dd3fc', defaultOpacity: 0.15 },
  2: { label: 'Tumor', color: '#FFFF00', defaultOpacity: 0.2 },
  3: { label: 'Cyst', color: '#22c55e', defaultOpacity: 0.15 },
}

export const SURFACE_LAYER_COLORS: Record<number, string> = {
  1: LAYER_META[1].color,
  2: LAYER_META[2].color,
  3: LAYER_META[3].color,
}

export const PHASE_PRIORITY: CanonicalPhase[] = ['NP', 'CMP', 'NC', 'EXC', 'DELAY', 'UNK']

export function describeSlice(axis: string, index: number, maxIndex: number): string {
  return `${axis.toUpperCase()} ${index + 1} / ${maxIndex + 1}`
}

export function compactCaseLabel(caseId: string): string {
  const match = caseId.match(/(\d{3,})$/)
  return match ? `#${match[1]}` : caseId
}

export function formatStatus(status: string | null | undefined): string {
  if (!status) {
    return 'Not reviewed'
  }
  return status.replaceAll('_', ' ')
}

export function statusChipColor(
  status: string | null | undefined,
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

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return '-'
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return parsed.toLocaleString()
}

export function sortInventoryRows(rows: CaseInventoryRow[]): CaseInventoryRow[] {
  return [...rows].sort((left, right) => {
    const phaseDelta =
      PHASE_PRIORITY.indexOf(left.canonical_phase) - PHASE_PRIORITY.indexOf(right.canonical_phase)
    if (phaseDelta !== 0) {
      return phaseDelta
    }
    const scanDelta = (left.scan_idx ?? '').localeCompare(right.scan_idx ?? '', undefined, {
      numeric: true,
    })
    if (scanDelta !== 0) {
      return scanDelta
    }
    return (left.side ?? '').localeCompare(right.side ?? '')
  })
}

export function sourceLabel(row: CaseInventoryRow | null, scope: Scope): string {
  if (!row) {
    return 'No source selected'
  }
  const source = scope === 'voi' ? `VOI${row.side ? ` ${row.side}` : ''}` : 'Complete CT'
  return [
    row.canonical_phase,
    row.scan_idx ? `scan ${row.scan_idx}` : null,
    source,
  ]
    .filter(Boolean)
    .join(' · ')
}

export function pathStatusLabel(status: string | null | undefined): string {
  if (!status) {
    return 'not provided'
  }
  return status.replaceAll('_', ' ')
}

export function latestDecisionForRow(
  decisions: CurationDecision[],
  rowId: string | null,
): CurationDecision | null {
  const ordered = [...decisions].sort((left, right) =>
    right.reviewed_at.localeCompare(left.reviewed_at),
  )
  return ordered.find((decision) => decision.row_id === rowId) ?? ordered[0] ?? null
}

export function quickStatusForButton(status: CurationStatus): string {
  if (status === 'accepted') {
    return 'Accept'
  }
  if (status === 'needs_major_correction') {
    return 'Needs correction'
  }
  if (status === 'rejected') {
    return 'Reject'
  }
  if (status === 'cannot_assess') {
    return 'Cannot assess'
  }
  return formatStatus(status)
}

export function isMissingSegWarning(code: string | null | undefined): boolean {
  if (!code) {
    return false
  }
  return code.toLowerCase().includes('missing_seg')
}

export function hasBlockingMissingSeg(row: CaseInventoryRow | null): boolean {
  if (!row) {
    return false
  }
  return row.seg_path.status !== 'exists' || row.qc_warnings.some((warning) => isMissingSegWarning(warning.code))
}
