// VOI extractor: how the task tab's draft settings (`voi.extract` settings) are read and changed —
// labels, the box preset and the reviewer's per-scan decisions (`overrides`).
import type { LabelDef, SegmentationSet, VoiCandidate, VoiCandidates, VoiRegion, VoiRequest } from '../../api'

export type Values = Record<string, unknown>

export interface Override {
  item_id: string
  swap?: boolean
  exclude?: string[]
}

export type BoxMode = 'recommended' | 'tight' | 'custom'

const str = (v: unknown, fallback: string) => (typeof v === 'string' && v ? v : fallback)
const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const strList = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : null)
const numTriple = (v: unknown): [number, number, number] | null =>
  Array.isArray(v) && v.length === 3 && v.every((x) => typeof x === 'number') ? (v as [number, number, number]) : null

export const regionOf = (values: Values): VoiRegion['id'] => str(values.region, 'kidney') as VoiRegion['id']
export const resampleOf = (values: Values) => num(values.resample_mm) ?? 1
export const keepLabelsOf = (values: Values) => values.keep_labels !== false
export const skipExistingOf = (values: Values) => values.skip_existing !== false
export const overridesOf = (values: Values): Override[] =>
  Array.isArray(values.overrides) ? (values.overrides as Override[]).filter((o) => o && typeof o.item_id === 'string') : []

/** Project labels the segmentation set still has (not removed there) */
export function activeLabels(labelMap: readonly LabelDef[], set: Pick<SegmentationSet, 'label_mapping' | 'removed_labels'> | undefined): LabelDef[] {
  const entries = Object.entries(set?.label_mapping ?? {})
  const removed = new Set(set?.removed_labels ?? [])
  return labelMap.filter((l) => {
    if (l.value <= 0) return false
    const inFile = entries.length ? entries.filter(([, v]) => v === l.value).map(([k]) => Number(k)) : [l.value]
    return inFile.some((v) => !removed.has(v))
  })
}

/** The labels that make up the VOI: the reviewer's pick (`labels`), else the region's when the set has its organ */
export function chosenLabels(values: Values, region: Pick<VoiRegion, 'labels' | 'organ'> | undefined, available: readonly string[]): string[] {
  const byLower = new Map(available.map((n) => [n.toLowerCase(), n]))
  const picked = strList(values.labels)
  if (picked) return picked.flatMap((n) => byLower.get(n.toLowerCase()) ?? [])
  if (!region?.organ.some((o) => byLower.has(o.toLowerCase()))) return []
  return region.labels.flatMap((n) => byLower.get(n.toLowerCase()) ?? [])
}

/** A label name that says its side (`kidney_left`), so sides need not come from position */
export const namesSide = (name: string) => /(^|[_-])(left|right)([_-]|$)/i.test(name)

/** Recommended = the region's margin and size (unset); Tight = 0 everywhere; else Custom */
export function boxMode(values: Values): BoxMode {
  const margin = num(values.margin_mm)
  const size = numTriple(values.min_size_mm)
  if (margin === null && !size) return 'recommended'
  if (margin === 0 && size && size.every((v) => v === 0)) return 'tight'
  return 'custom'
}

/** The margin and size the server will use, for display and the request */
export function effectiveBox(values: Values, region: Pick<VoiRegion, 'margin_mm' | 'min_size_mm'> | undefined): { margin: number; size: [number, number, number] } {
  return {
    margin: num(values.margin_mm) ?? region?.margin_mm ?? 0,
    size: numTriple(values.min_size_mm) ?? (region ? ([...region.min_size_mm] as [number, number, number]) : [0, 0, 0]),
  }
}

export function withBoxMode(values: Values, mode: BoxMode, region: Pick<VoiRegion, 'margin_mm' | 'min_size_mm'> | undefined): Values {
  const rest = Object.fromEntries(Object.entries(values).filter(([k]) => k !== 'margin_mm' && k !== 'min_size_mm'))
  if (mode === 'recommended') return rest
  if (mode === 'tight') return { ...rest, margin_mm: 0, min_size_mm: [0, 0, 0] }
  const box = effectiveBox(values, region)
  return { ...rest, margin_mm: box.margin, min_size_mm: box.size }
}

/** What the candidates endpoint needs; `labels` is the resolved list (never empty when sent) */
export function requestOf(values: Values, segId: string | null, labels: string[]): VoiRequest {
  return {
    seg_id: segId,
    region: regionOf(values),
    labels,
    margin_mm: num(values.margin_mm),
    min_size_mm: numTriple(values.min_size_mm),
  }
}

/** Region, labels and segmentation set decide what is detected; margin and size only reframe */
export const detectionKey = (values: Values, segId: string | null, labels: readonly string[]) => JSON.stringify([regionOf(values), segId, labels])

const overrideOf = (values: Values, itemId: string) => overridesOf(values).find((o) => o.item_id === itemId)
export const isSwapped = (values: Values, itemId: string) => overrideOf(values, itemId)?.swap === true
export const isExcluded = (values: Values, itemId: string, candidateId: string) => (overrideOf(values, itemId)?.exclude ?? []).includes(candidateId)

function setOverride(values: Values, itemId: string, patch: (o: Override) => Override): Values {
  const cur = overrideOf(values, itemId) ?? { item_id: itemId }
  const next = patch(cur)
  const keep = next.swap || next.exclude?.length
  const others = overridesOf(values).filter((o) => o.item_id !== itemId)
  const overrides = keep ? [...others, { item_id: itemId, ...(next.swap ? { swap: true } : {}), ...(next.exclude?.length ? { exclude: next.exclude } : {}) }] : others
  return overrides.length ? { ...values, overrides } : Object.fromEntries(Object.entries(values).filter(([k]) => k !== 'overrides'))
}

export const toggleSwap = (values: Values, itemId: string) => setOverride(values, itemId, (o) => ({ ...o, swap: !o.swap }))
export const toggleExclude = (values: Values, itemId: string, candidateId: string) =>
  setOverride(values, itemId, (o) => {
    const cur = o.exclude ?? []
    return { ...o, exclude: cur.includes(candidateId) ? cur.filter((c) => c !== candidateId) : [...cur, candidateId] }
  })

/** Decisions on scans outside the selection, or on VOIs the detector no longer finds (`found`:
 *  candidate ids per prepared scan; scans still loading are not judged) */
export function orphanOverrides(values: Values, selection: ReadonlySet<string>, found: ReadonlyMap<string, readonly string[]>): Override[] {
  return overridesOf(values).filter((o) => {
    if (!selection.has(o.item_id)) return true
    const ids = found.get(o.item_id)
    return !!ids && (o.exclude ?? []).some((c) => !ids.includes(c))
  })
}

export function dropOverrides(values: Values, drop: readonly Override[]): Values {
  const gone = new Set(drop.map((o) => o.item_id))
  const overrides = overridesOf(values).filter((o) => !gone.has(o.item_id))
  return overrides.length ? { ...values, overrides } : Object.fromEntries(Object.entries(values).filter(([k]) => k !== 'overrides'))
}

/** The side shown after the reviewer's swap */
export function shownSide(c: Pick<VoiCandidate, 'side'>, swapped: boolean): VoiCandidate['side'] {
  if (!swapped || !c.side) return c.side
  return c.side === 'L' ? 'R' : 'L'
}

/** The side's confidence as shown: a reviewer's swap replaces the engine's */
export const sideConfidence = (engine: string | undefined, swapped: boolean) => (engine ? (swapped ? 'reviewer' : engine) : '')

/** Where the detector took the side from, for the card's details */
export function sideSource(c: Pick<VoiCandidate, 'warnings'>, labels: readonly string[]): 'anatomy' | 'names' | 'position' {
  if (c.warnings.includes('sides_from_anatomy')) return 'anatomy'
  return labels.some(namesSide) ? 'names' : 'position'
}

/** A VOI the reviewer should look at: an uncertain side or any warning */
export const needsReview = (c: Pick<VoiCandidate, 'side' | 'confidence' | 'warnings'>) => (!!c.side && c.confidence === 'uncertain') || c.warnings.length > 0

/** What the review keeps of a scan's VOIs once found: enough to count, filter and match decisions */
export interface CandFlags {
  id: string
  uncertain: boolean // a lateral VOI whose side is uncertain
  warned: boolean
}

export const flagsOf = (data: VoiCandidates): CandFlags[] =>
  data.candidates.map((c) => ({ id: c.id, uncertain: !!c.side && c.confidence === 'uncertain', warned: c.warnings.length > 0 }))

export const flaggedScan = (cands: readonly CandFlags[] | undefined) => !!cands?.some((c) => c.uncertain || c.warned)

export interface ReviewCounts {
  scans: number
  prepared: number
  failed: number
  vois: number
  included: number
  excluded: number
  uncertain: number
  warnings: number
  needsReview: number
}

export function reviewCounts(values: Values, items: readonly { itemId: string; cands?: readonly CandFlags[]; failed: boolean }[]): ReviewCounts {
  const out: ReviewCounts = { scans: items.length, prepared: 0, failed: 0, vois: 0, included: 0, excluded: 0, uncertain: 0, warnings: 0, needsReview: 0 }
  for (const it of items) {
    if (it.failed) out.failed++
    if (!it.cands) continue
    out.prepared++
    for (const c of it.cands) {
      out.vois++
      if (isExcluded(values, it.itemId, c.id)) out.excluded++
      else out.included++
      if (c.uncertain && !isSwapped(values, it.itemId)) out.uncertain++
      if (c.warned) out.warnings++
    }
    if (flaggedScan(it.cands)) out.needsReview++
  }
  return out
}

/** `x × y × z mm`, axes right–left, anterior–posterior, superior–inferior */
export const fmtSize = (mm: readonly number[]) => `${mm.map((v) => Math.round(v)).join(' × ')} mm`

/** Warning codes with their own text; others show as the code */
export const WARNING_CODES = [
  'mask_header_differs',
  'sides_from_anatomy',
  'label_side_mismatch',
  'at_image_edge',
  'side_ambiguous',
  'split_at_midline',
  'both_on_one_side_of_midline',
  'midline_from_grid',
  'oblique_grid',
  'protected_component_merged',
] as const
