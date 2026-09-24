// Window/level math (VW-05). Presets live in state/viewerSync (WL_PRESETS).
import type { ItemRecord } from '../../../api'

/** HU presets apply only to CT (`item.modality`). A missing modality counts as CT (this is a CT workbench). */
export function isCt(item: Pick<ItemRecord, 'modality'>): boolean {
  const m = item.modality
  return typeof m !== 'string' || m.trim() === '' || m.trim().toUpperCase() === 'CT'
}

/** Modalities the user can pick when the item has none (VW-05); `OT` = other (percentile window) */
export const MODALITY_CHOICES = ['CT', 'MR', 'OT'] as const

/** Identity of an item for the display-only modality choice (Open-mode ids repeat across sessions) */
export const modalityKey = (item: Pick<ItemRecord, 'item_id' | 'case_id' | 'image'>): string =>
  `${item.case_id}|${item.item_id}|${item.image?.ref ?? ''}`

/** VW-05: a known modality wins; an unknown one is the user's choice, else the project default
 *  (PRJ-14; `mixed` assumes CT), else assumed CT */
export function effectiveModality(
  item: Pick<ItemRecord, 'item_id' | 'case_id' | 'image' | 'modality'>,
  overrides: Record<string, string>,
  fallback = 'CT',
): { value: string; assumed: boolean } {
  const known = typeof item.modality === 'string' && item.modality.trim() !== '' ? item.modality.trim().toUpperCase() : null
  if (known) return { value: known, assumed: false }
  return { value: overrides[modalityKey(item)] ?? (fallback === 'MR' ? 'MR' : 'CT'), assumed: true }
}

/** VW-22: the DICOM header window `[ww, wl]` of an item (converter row facts or Open-mode probe) */
export function dicomWindowOf(item: Pick<ItemRecord, 'extra'>): [number, number] | null {
  const ww = Number(item.extra?.window_width)
  const wl = Number(item.extra?.window_center)
  return Number.isFinite(ww) && ww > 0 && Number.isFinite(wl) && item.extra?.window_width !== '' ? [ww, wl] : null
}

/** Right-drag: horizontal = width, vertical = level (up = brighter → lower level) */
export function dragWindow(start: [number, number], dx: number, dy: number, range: number): [number, number] {
  // Scale with the data range so MR (0..4000) and CT (−1024..3071) both feel natural
  const k = Math.max(0.5, range / 1000)
  const ww = Math.max(1, Math.round(start[0] + dx * 2 * k))
  const wl = Math.round(start[1] - dy * k)
  return [ww, wl]
}

/**
 * 1st–99th percentile window for non-CT images. Sampled (≤ 2^18 voxels) so it stays cheap on
 * 512×512×600 volumes. Returns [ww, wl].
 */
export function percentileWindow(data: ArrayLike<number>, slope = 1, inter = 0, lo = 0.01, hi = 0.99): [number, number] {
  const n = data.length
  if (n === 0) return [1, 0]
  const step = Math.max(1, Math.floor(n / 262144))
  const sample: number[] = []
  for (let i = 0; i < n; i += step) sample.push((data[i] ?? 0) * slope + inter)
  sample.sort((a, b) => a - b)
  const at = (q: number) => sample[Math.min(sample.length - 1, Math.max(0, Math.round(q * (sample.length - 1))))] ?? 0
  const a = at(lo)
  const b = at(hi)
  const ww = Math.max(1, b - a)
  return [round(ww), round(a + ww / 2)]
}

const round = (v: number) => (Math.abs(v) >= 10 ? Math.round(v) : Math.round(v * 100) / 100)

/** [ww, wl] → [cal_min, cal_max] */
export const windowToRange = (ww: number, wl: number): [number, number] => [wl - ww / 2, wl + ww / 2]
