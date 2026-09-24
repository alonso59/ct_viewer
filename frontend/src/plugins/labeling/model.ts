// Spreadsheet helpers for the label table editor (LBL-03): pure, unit-tested.
import type { LabelCellIn, LabelCellRow, LabelColumn } from '../../api'

export interface Pos {
  r: number
  c: number
}

/** Rows × columns of a clipboard text (tabs between cells, new lines between rows). */
export function parseTsv(text: string): string[][] {
  const lines = text.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n')
  return lines.map((l) => l.split('\t'))
}

/** Cells written by pasting `grid` at `at` (clipped to the table). */
export function pasteCells(grid: string[][], at: Pos, rows: LabelCellRow[], cols: LabelColumn[]): LabelCellIn[] {
  const out: LabelCellIn[] = []
  grid.forEach((line, i) =>
    line.forEach((v, j) => {
      const row = rows[at.r + i]
      const col = cols[at.c + j]
      if (row && col) out.push({ column_id: col.column_id, target: row.target, value: v.trim() === '' ? null : v.trim() })
    }),
  )
  return out
}

/** The rectangle between two corners (inclusive). */
export function rect(a: Pos, b: Pos): { r0: number; r1: number; c0: number; c1: number } {
  return { r0: Math.min(a.r, b.r), r1: Math.max(a.r, b.r), c0: Math.min(a.c, b.c), c1: Math.max(a.c, b.c) }
}

/** Bulk fill (or clear with `null`) of a selection. */
export function fillCells(a: Pos, b: Pos, value: unknown, rows: LabelCellRow[], cols: LabelColumn[]): LabelCellIn[] {
  const { r0, r1, c0, c1 } = rect(a, b)
  const out: LabelCellIn[] = []
  for (let r = r0; r <= r1; r++)
    for (let c = c0; c <= c1; c++) {
      const row = rows[r]
      const col = cols[c]
      if (row && col) out.push({ column_id: col.column_id, target: row.target, value })
    }
  return out
}

/** Arrow-key move, clamped. */
export function move(p: Pos, key: string, nRows: number, nCols: number): Pos {
  const d: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1], Tab: [0, 1], Enter: [1, 0] }
  const [dr, dc] = d[key] ?? [0, 0]
  return { r: Math.max(0, Math.min(nRows - 1, p.r + dr)), c: Math.max(0, Math.min(nCols - 1, p.c + dc)) }
}

/** Display text of a value (LBL-02 types). */
export function display(col: LabelColumn, v: unknown): string {
  if (v == null) return ''
  if (col.type === 'bool') return v ? '✓' : '✗'
  if (col.type === 'number' && col.unit) return `${String(v)} ${col.unit}`
  return String(v)
}

/** Rows kept by per-column text filters (case-insensitive "contains"; `'-'` = empty). */
export function filterRows(rows: LabelCellRow[], cols: LabelColumn[], filters: Record<string, string>, q: string): LabelCellRow[] {
  const active = Object.entries(filters).filter(([, f]) => f.trim())
  return rows.filter((r) => {
    if (q && !r.target.toLowerCase().includes(q.toLowerCase())) return false
    return active.every(([cid, f]) => {
      const col = cols.find((c) => c.column_id === cid)
      const text = col ? display(col, r.values?.[cid]) : ''
      return f.trim() === '-' ? text === '' : text.toLowerCase().includes(f.trim().toLowerCase())
    })
  })
}

export function sortRows(rows: LabelCellRow[], colId: string | null, dir: 1 | -1): LabelCellRow[] {
  if (!colId) return rows
  const key = (r: LabelCellRow) => (colId === '__target' ? r.target : r.values?.[colId])
  return [...rows].sort((a, b) => {
    const x = key(a)
    const y = key(b)
    if (x == null && y == null) return 0
    if (x == null) return 1
    if (y == null) return -1
    return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true })) * dir
  })
}
