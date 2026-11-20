import type { TFunction } from 'i18next'

import type { ItemRecord } from '../api'

export type ScanGroup =
  | { kind: 'exam'; key: string; uid: string; day: number | null; ordinal: number | null }
  | { kind: 'series'; key: string; uid: string; number: string | null; description: string }
  | { kind: 'other'; key: string }
  | { kind: 'scan'; key: string; index: string }

/** A scan with the groups it sits under (outermost first) and its series part (`t2`, `b800`) */
export interface GroupedScan {
  scanIdx: string
  part: string | null
  groups: ScanGroup[]
  items: ItemRecord[]
}

interface Facts {
  scanIdx: string
  items: ItemRecord[]
  study: string | null
  series: string | null
  part: string | null
  number: string | null
  day: number | null
  description: string
}

const text = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : typeof v === 'number' ? String(v) : null)
const byNumber = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true })
/** Missing values sort last */
const nullsLast = <T,>(a: T | null, b: T | null, cmp: (x: T, y: T) => number) => (a === null ? (b === null ? 0 : 1) : b === null ? -1 : cmp(a, b))
const lowest = (fs: Facts[]) => fs.map((f) => f.scanIdx).sort(byNumber)[0] ?? ''

function factsOf(scanIdx: string, items: ItemRecord[]): Facts {
  // VOI items carry no DICOM facts; the full-volume item does
  const src = items.find((i) => i.scope === 'complete') ?? items[0]!
  const extra = src.extra ?? {}
  const uid = text(extra.series_uid)
  const hash = uid ? uid.indexOf('#') : -1
  const day = Number(text(extra.days_from_first_scan) ?? NaN)
  return {
    scanIdx,
    items,
    study: text(extra.study_uid),
    series: uid && hash >= 0 ? uid.slice(0, hash) : uid,
    part: uid && hash >= 0 ? uid.slice(hash + 1).replace(/(\d)\.0+(?=\D|$)/g, '$1') : null,
    number: text(extra.series_number),
    day: Number.isFinite(day) ? day : null,
    description: text(extra.series_description) ?? '',
  }
}

/**
 * A case's scans grouped by DICOM exam, then series, then part, in reading order. A level with a
 * single child is left out, and a case without exam facts stays flat in scan order.
 */
export function groupScans(items: ItemRecord[]): GroupedScan[] {
  const byScan = new Map<string, ItemRecord[]>()
  for (const i of items) byScan.set(i.scan_idx, [...(byScan.get(i.scan_idx) ?? []), i])
  const facts = [...byScan].map(([idx, its]) => factsOf(idx, its))
  const flat = (fs: Facts[], groups: ScanGroup[] = []) =>
    [...fs].sort((a, b) => byNumber(a.scanIdx, b.scanIdx)).map((f) => ({ scanIdx: f.scanIdx, part: f.part, groups, items: f.items }))
  if (!facts.some((f) => f.study)) return flat(facts)

  const exams = new Map<string, Facts[]>()
  for (const f of facts) if (f.study) exams.set(f.study, [...(exams.get(f.study) ?? []), f])
  const day = (fs: Facts[]) => {
    const days = fs.map((f) => f.day).filter((d): d is number => d !== null)
    return days.length ? Math.min(...days) : null
  }
  const ordered = [...exams].sort(([, a], [, b]) => nullsLast(day(a), day(b), (x, y) => x - y) || byNumber(lowest(a), lowest(b)))
  const other = facts.filter((f) => !f.study)
  const showExam = ordered.length > 1 || other.length > 0
  const seen = new Map<number, number>()
  const dayCount = new Map<number, number>()
  for (const [, fs] of ordered) {
    const d = day(fs)
    if (d !== null) dayCount.set(d, (dayCount.get(d) ?? 0) + 1)
  }

  const out: GroupedScan[] = []
  ordered.forEach(([uid, fs], position) => {
    const d = day(fs)
    const nth = d === null ? null : (seen.get(d) ?? 0) + 1
    if (d !== null) seen.set(d, nth!)
    const ordinal = d === null ? position + 1 : (dayCount.get(d) ?? 0) > 1 ? nth : null
    const exam: ScanGroup[] = showExam ? [{ kind: 'exam', key: `exam:${uid}`, uid, day: d, ordinal }] : []
    const series = new Map<string, Facts[]>()
    for (const f of fs) {
      const key = f.series ?? `scan:${f.scanIdx}`
      series.set(key, [...(series.get(key) ?? []), f])
    }
    const number = (s: Facts[]) => s.find((f) => f.number)?.number ?? null
    const sorted = [...series].sort(([, a], [, b]) => nullsLast(number(a), number(b), byNumber) || byNumber(lowest(a), lowest(b)))
    for (const [key, parts] of sorted) {
      const head = parts.find((f) => f.part === null)
      const rest = parts.filter((f) => f !== head).sort((a, b) => byNumber(a.scanIdx, b.scanIdx))
      const group: ScanGroup[] = parts.length > 1
        ? [{ kind: 'series', key: `series:${key}`, uid: key, number: number(parts), description: parts.find((f) => f.description)?.description ?? '' }]
        : []
      for (const f of head ? [head, ...rest] : rest) out.push({ scanIdx: f.scanIdx, part: f.part, groups: [...exam, ...group], items: f.items })
    }
  })
  return [...out, ...flat(other, [{ kind: 'other', key: 'other' }])]
}

/** "Exam · day 84", "Series 7 · e-THRIVE_dyn_BH", "Other scans" */
export function scanGroupLabel(t: TFunction, g: ScanGroup): string {
  if (g.kind === 'scan') return t('item.scanShort', { scan: g.index })
  if (g.kind === 'other') return t('scanGroup.other')
  if (g.kind === 'series') {
    const name = g.number ? t('scanGroup.series', { number: g.number }) : t('scanGroup.seriesUnnumbered')
    return g.description ? `${name} · ${g.description}` : name
  }
  if (g.day === null) return t('scanGroup.examNth', { n: g.ordinal })
  return g.ordinal ? t('scanGroup.examDayNth', { day: g.day, n: g.ordinal }) : t('scanGroup.examDay', { day: g.day })
}
