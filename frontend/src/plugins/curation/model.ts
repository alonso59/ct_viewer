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

/** Latest decisions that apply to the active item (item targets) and its case (case target) */
export function decisionsFor(rows: CurationStateRow[], itemId: string | null, caseId: string | null): CurationStateRow[] {
  if (!caseId) return []
  return rows
    .filter((r) => (itemId !== null && r.item_id === itemId) || (r.item_id === null && r.case_id === caseId))
    .sort((a, b) => b.at.localeCompare(a.at))
}

/** CUR-08 derived status of one (item, target); a case target has no item */
export function statusOf(rows: CurationStateRow[], itemId: string | null, caseId: string | null, target: string): CurationStatus {
  const caseTarget = target === 'case'
  const row = rows.find((r) =>
    caseTarget ? r.item_id === null && r.case_id === caseId && r.target === target : r.item_id === itemId && r.target === target,
  )
  return row?.status ?? 'not_reviewed'
}

