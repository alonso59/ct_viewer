// Problems panel (UI-09): QC warnings (IMP-08) grouped by case; click opens the item.
import { useTranslation } from 'react-i18next'

import { useWarnings, type QCWarning } from '../../api'
import { SeverityIcon, itemName, knownPhase } from '../../lib'
import { useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import i18n from '../../i18n'
import { openInContext } from './navigate'

export function groupWarnings(ws: QCWarning[]): [string, QCWarning[]][] {
  const m = new Map<string, QCWarning[]>()
  // Warnings without a case (e.g. a file-level parse error) group under ''
  for (const w of ws) m.set(w.case_id ?? '', [...(m.get(w.case_id ?? '') ?? []), w])
  return [...m.entries()].sort(([a], [b]) => a.localeCompare(b))
}

let cursor = -1
/** F8: open the next problem in case order */
export function nextProblem(ws: QCWarning[]) {
  const flat = groupWarnings(ws).flatMap(([, list]) => list)
  if (!flat.length) return
  cursor = (cursor + 1) % flat.length
  if (flat[cursor]?.case_id) openProblem(flat, cursor)
}

/** Opens a warning's item with the Problems list as navigation context (AUD-A1-04) */
function openProblem(flat: QCWarning[], i: number) {
  const withCase = flat.filter((w) => w.case_id)
  const at = withCase.indexOf(flat[i] as QCWarning)
  openInContext(i18n.t('panel.problems'), withCase.map((w) => ({ caseId: w.case_id ?? '', itemId: w.item_id })), at, true)
}

export function ProblemsPanel() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { data, isLoading } = useWarnings(pid)
  if (isLoading) return <div className="empty">{t('common.loading')}</div>
  if (!data?.length) return <div className="empty">{t('problems.none')}</div>
  const flat = groupWarnings(data).flatMap(([, list]) => list)
  return (
    <div role="tree" aria-label={t('panel.problems')} className="panel-size">
      {groupWarnings(data).map(([cid, list]) => (
        <div key={cid} role="group">
          <div className="list-row" style={{ cursor: 'default', paddingLeft: 8 }} role="treeitem" aria-expanded>
            <Icon spec={codicon('chevron-down')} />
            <span className="mono">{cid || t('problems.projectLevel')}</span>
            <span className="count">{list.length}</span>
          </div>
          {list.map((w) => (
            <button key={`${w.code}-${w.item_id ?? ''}-${w.field ?? ''}`} type="button" role="treeitem" className="list-row" style={{ paddingLeft: 32 }} disabled={!w.case_id} onClick={() => w.case_id && openProblem(flat, flat.indexOf(w))}>
              <SeverityIcon severity={w.severity} />
              <span>{t(`warning.${w.code}`)}</span>
              <span className="muted">{w.message}</span>
              <span className="muted problem-where" title={w.item_id ? `${w.code} · ${w.item_id}` : w.code}>
                {w.item_id ? itemName(w.item_id, t, knownPhase(pid, w.item_id)) : null}
              </span>
            </button>
          ))}
        </div>
      ))}
    </div>
  )
}

export function useProblemsBadge(): number | null {
  const pid = useWorkbench((s) => s.pid) ?? ''
  return useWarnings(pid).data?.length ?? null
}
