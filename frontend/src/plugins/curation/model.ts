// Pure curation helpers (CUR-03, CUR-08): targets and decisions of the active item/case. Phase is
// not a curation target (ADR-0026, PHASE.md).
import { type CurationStateRow, type CurationStatus, type ItemRecord, type LabelDef } from '../../api'

export interface TargetOption {
  value: string
  /** i18n key, or `label:{name}` for label-map entries */
  label: string
}

/** CUR-03 targets: the whole mask, each label of the project map (PRJ-07), VOI mask, side, case */
export function targetsFor(item: Pick<ItemRecord, 'scope'> | undefined, labels: Pick<LabelDef, 'value' | 'name'>[]): TargetOption[] {
  const out: TargetOption[] = [{ value: 'seg', label: 'curation.target.seg' }]
  for (const l of labels) out.push({ value: `label:${l.value}`, label: `label:${l.name}` })
  if (item?.scope === 'voi') out.push({ value: 'voi_mask', label: 'curation.target.voi_mask' })
  out.push(
    { value: 'side', label: 'curation.target.side' },
    { value: 'case', label: 'curation.target.case' },
  )
  return out
}

const isMask = (t: string) => t === 'seg' || t === 'voi_mask' || t.startsWith('label:')
/** A row's set: mask targets without one mean `imported` (CURATION §Targets) */
const rowSeg = (r: CurationStateRow) => (isMask(r.target) ? (r.seg_id ?? 'imported') : null)

/** Latest decisions that apply to the active item (item targets) and its case (case target);
 *  mask targets only of the set on screen, `seg` (VW-19, ADR-0015; AUD-A5-06) */
export function decisionsFor(rows: CurationStateRow[], itemId: string | null, caseId: string | null, seg: string): CurationStateRow[] {
  if (!caseId) return []
  return rows
    .filter((r) => ((itemId !== null && r.item_id === itemId) || (r.item_id === null && r.case_id === caseId)) && (!isMask(r.target) || rowSeg(r) === seg))
    .sort((a, b) => b.at.localeCompare(a.at))
}

/** CUR-08 derived status of one (item, target, seg); a case target has no item, only mask
 *  targets have a set */
export function statusOf(rows: CurationStateRow[], itemId: string | null, caseId: string | null, target: string, seg: string): CurationStatus {
  const caseTarget = target === 'case'
  const want = isMask(target) ? seg : null
  const row = rows.find((r) =>
    (caseTarget ? r.item_id === null && r.case_id === caseId : r.item_id === itemId) && r.target === target && rowSeg(r) === want,
  )
  return row?.status ?? 'not_reviewed'
}

