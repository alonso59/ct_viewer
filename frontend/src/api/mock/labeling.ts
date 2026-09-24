// Mock labeling tables (API-56..58): in memory, same rules as the backend (LBL-01..05), enough
// for the prototype and unit tests.
import { ProblemError } from '../problem'
import type { ItemRecord, LabelCellEvent, LabelCellIn, LabelCellRow, LabelColumn, LabelTable, LabelTableCreate, LabelTableInfo, LabelTablePatch } from '../types'

type Table = Omit<LabelTable, 'columns'> & { columns: LabelColumn[] }
interface Store {
  tables: Table[]
  events: LabelCellEvent[]
}
const stores = new Map<string, Store>()
let seq = 0
const id = () => `01MOCKLBL${String(++seq).padStart(17, '0')}`
const now = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z')
const store = (pid: string) => stores.get(pid) ?? (stores.set(pid, { tables: [], events: [] }), stores.get(pid)!)
const slug = (name: string, taken: string[]) => {
  const base = name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'col'
  let s = /^[a-z]/.test(base) ? base : `c_${base}`
  for (let n = 2; taken.includes(s); n++) s = `${base}_${n}`
  return s
}

export function targets(t: Pick<LabelTable, 'level'>, items: ItemRecord[]): { target: string; case_id: string; item_id: string }[] {
  const out = new Map<string, { target: string; case_id: string; item_id: string }>()
  for (const i of items.filter((x) => x.status !== 'excluded_upstream')) {
    const key = t.level === 'case' ? i.case_id : t.level === 'scan' ? `${i.case_id}.${i.scan_idx}` : i.item_id
    if (!out.has(key) || (t.level !== 'item' && i.scope === 'complete' && !out.get(key)!.item_id.endsWith('.complete.-'))) out.set(key, { target: key, case_id: i.case_id, item_id: i.item_id })
  }
  return [...out.values()]
}

function state(s: Store, tid: string): Map<string, LabelCellEvent> {
  const m = new Map<string, LabelCellEvent>()
  for (const e of s.events) {
    if (e.table_id !== tid) continue
    if (e.value == null) m.delete(`${e.column_id}|${e.target}`)
    else m.set(`${e.column_id}|${e.target}`, e)
  }
  return m
}

function coerce(c: LabelColumn, v: unknown): unknown {
  if (v == null || v === '') return null
  if (c.type === 'bool') {
    const t = String(v).toLowerCase()
    if (v === true || ['true', 'yes', 'y', '1'].includes(t)) return true
    if (v === false || ['false', 'no', 'n', '0'].includes(t)) return false
    throw new Error('expected yes/no')
  }
  if (c.type === 'number') {
    const x = Number(String(v).replace(',', '.'))
    if (!Number.isFinite(x)) throw new Error('expected a number')
    return x
  }
  if (c.type === 'category' && c.levels?.length && !c.levels.includes(String(v))) throw new Error('not a level')
  return String(v)
}

export const mockLabeling = {
  list(pid: string, items: ItemRecord[]): LabelTableInfo[] {
    const s = store(pid)
    return s.tables.map((t) => {
      const rows = new Set(targets(t, items).map((r) => r.target))
      const st = state(s, t.table_id)
      return { ...structuredClone(t), n_rows: rows.size, progress: t.columns.filter((c) => !c.hidden).map((c) => ({ column_id: c.column_id, filled: [...st.values()].filter((e) => e.column_id === c.column_id && rows.has(e.target)).length })) }
    })
  },
  create(pid: string, body: LabelTableCreate): LabelTable {
    const s = store(pid)
    const at = now()
    const cols: LabelColumn[] = []
    for (const c of body.columns ?? []) cols.push({ column_id: id(), slug: slug(c.name, cols.map((x) => x.slug)), name: c.name, type: c.type ?? 'text', levels: c.levels ?? [], unit: c.unit ?? null, min: c.min ?? null, max: c.max ?? null, description: c.description ?? '', default: null, hidden: false })
    const t: Table = { table_id: id(), slug: slug(body.name, s.tables.map((x) => x.slug)), name: body.name, level: body.level, columns: cols, created_at: at, updated_at: at }
    s.tables.push(t)
    return structuredClone(t)
  },
  patch(pid: string, tid: string, body: LabelTablePatch): LabelTable {
    const t = store(pid).tables.find((x) => x.table_id === tid)
    if (!t) throw new ProblemError(404, 'not-found', 'Label table not found', tid)
    if (body.name) t.name = body.name
    for (const c of body.columns ?? []) {
      const cur = t.columns.find((x) => x.column_id === c.column_id)
      if (cur) Object.assign(cur, { name: c.name, hidden: c.hidden ?? cur.hidden, levels: c.levels ?? cur.levels })
      else t.columns.push({ column_id: id(), slug: slug(c.name, t.columns.map((x) => x.slug)), name: c.name, type: c.type ?? 'text', levels: c.levels ?? [], unit: c.unit ?? null, min: c.min ?? null, max: c.max ?? null, description: '', default: null, hidden: false })
    }
    t.updated_at = now()
    return structuredClone(t)
  },
  cells(pid: string, tid: string, items: ItemRecord[]): LabelCellRow[] {
    const s = store(pid)
    const t = s.tables.find((x) => x.table_id === tid)
    if (!t) throw new ProblemError(404, 'not-found', 'Label table not found', tid)
    const st = state(s, tid)
    return targets(t, items).map((r) => {
      const row: LabelCellRow = { ...r, values: {}, updated: {} }
      for (const c of t.columns.filter((x) => !x.hidden)) {
        const e = st.get(`${c.column_id}|${r.target}`)
        if (e) {
          row.values![c.column_id] = e.value
          row.updated![c.column_id] = e.reviewer
        }
      }
      return row
    })
  },
  write(pid: string, tid: string, cells: LabelCellIn[], reviewer: string, sessionId: string): LabelCellEvent[] {
    const s = store(pid)
    const t = s.tables.find((x) => x.table_id === tid)
    if (!t) throw new ProblemError(404, 'not-found', 'Label table not found', tid)
    const out = cells.map((c) => {
      const col = t.columns.find((x) => x.column_id === c.column_id)
      if (!col) throw new ProblemError(422, 'validation', 'Unknown column', c.column_id)
      let value: unknown
      try {
        value = coerce(col, c.value)
      } catch (e) {
        throw new ProblemError(422, 'validation', 'Invalid cell', `${c.target}: ${(e as Error).message}`)
      }
      return { event_id: id(), at: now(), reviewer, session_id: sessionId, table_id: tid, column_id: c.column_id, target: c.target, value } satisfies LabelCellEvent
    })
    s.events.push(...out)
    return out
  },
  history(pid: string, tid: string, target?: string, col?: string): LabelCellEvent[] {
    return store(pid).events.filter((e) => e.table_id === tid && (!target || e.target === target) && (!col || e.column_id === col)).reverse()
  },
}
