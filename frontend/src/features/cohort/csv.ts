import type { CohortCaseRow, Variable } from '../../api'

const cell = (v: string | number | null | undefined): string => {
  const s = v == null ? '' : String(v)
  return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s
}

/** The grid as CSV: one row per scan under the chosen columns. Sensitive variables stay out unless
 *  `withSensitive`; only the case, scan, phase and modality identify a row (no paths, UIDs or blobs). */
export function gridCsv(columns: Variable[], rows: CohortCaseRow[], withSensitive: boolean): string {
  const shown = columns.filter((v) => withSensitive || !v.tags.includes('sensitive'))
  const head = ['case_id', 'scan', 'phase', 'modality', ...shown.map((v) => v.name)]
  const body = rows.flatMap((c) =>
    (c.scans ?? []).map((s) => [c.case_id, s.scan_idx, s.phase, s.modality, ...shown.map((v) => s.values?.[v.name])]),
  )
  return `${[head, ...body].map((r) => r.map(cell).join(',')).join('\n')}\n`
}
