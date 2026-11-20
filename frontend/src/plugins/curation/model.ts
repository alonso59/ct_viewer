import type { TFunction } from 'i18next'

import { parseItemId } from '../../lib'

import { type CurationStateRow, type CurationStatus, type ItemRecord, type LabelDef } from '../../api'

/** Targets: the whole mask, each label of the project map, VOI mask, side, case */
export function targetsFor(item: Pick<ItemRecord, 'scope'> | undefined, labels: Pick<LabelDef, 'value' | 'name'>[]): string[] {
  return ['seg', ...labels.map((l) => `label:${l.value}`), ...(item?.scope === 'voi' ? ['voi_mask'] : []), 'side', 'scan', 'case']
}

const TARGET_KEYS: Record<string, string> = {
  seg: 'curation.target.seg',
  voi_mask: 'curation.target.voi_mask',
  side: 'curation.target.side',
  case: 'curation.target.case',
  scan: 'curation.target.scan',
}

/** A target in words ("Segmentation (all labels)", "Label: kidney"); the raw target stays in tooltips */
export function targetName(target: string, labels: Pick<LabelDef, 'value' | 'name'>[], t: TFunction, scan?: string | null): string {
  if (target === 'scan' && scan) return t('curation.target.scanIndex', { scan })
  if (target.startsWith('label:')) return t('curation.target.labelName', { name: labels.find((l) => `label:${l.value}` === target)?.name ?? target.slice(6) })
  const key = TARGET_KEYS[target]
  return key ? t(key) : target
}

/** Mask targets carry `seg_id` */
export const isMask = (t: string) => t === 'seg' || t === 'voi_mask' || t.startsWith('label:')
/** A row's set: mask targets without one mean `imported` */
const rowSeg = (r: CurationStateRow) => (isMask(r.target) ? (r.seg_id ?? 'imported') : null)

function appliesTo(row: CurationStateRow, itemId: string | null, caseId: string | null): boolean {
  if (row.case_id !== caseId) return false
  if (row.target === 'case') return true
  if (row.target === 'scan') return !!itemId && row.scan_idx === parseItemId(itemId)?.scan_idx
  return itemId !== null && row.item_id === itemId
}

/** Latest decisions that apply to the active item (item targets) and its case (case target);
 *  mask targets only of the set on screen, `seg` */
export function decisionsFor(rows: CurationStateRow[], itemId: string | null, caseId: string | null, seg: string): CurationStateRow[] {
  if (!caseId) return []
  return rows
    .filter((r) => appliesTo(r, itemId, caseId) && (!isMask(r.target) || rowSeg(r) === seg))
    .sort((a, b) => b.at.localeCompare(a.at))
}

/** Derived status of one (item, target, seg); a case target has no item, only mask
 *  targets have a set */
/** The current decision for an item (or the case) and target; mask targets per segmentation set */
export function rowOf(rows: CurationStateRow[], itemId: string | null, caseId: string | null, target: string, seg: string): CurationStateRow | undefined {
  const want = isMask(target) ? seg : null
  return rows.find((r) =>
    r.target === target && appliesTo(r, itemId, caseId) && rowSeg(r) === want,
  )
}

export function statusOf(rows: CurationStateRow[], itemId: string | null, caseId: string | null, target: string, seg: string): CurationStatus {
  return rowOf(rows, itemId, caseId, target, seg)?.status ?? 'not_reviewed'
}

