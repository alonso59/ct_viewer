// Problems panel (UI-09): QC warnings (IMP-08) grouped by case; click opens the item.
import { useTranslation } from 'react-i18next'

import { useWarnings, type QCWarning } from '../../api'
import { SeverityIcon } from '../../lib'
import { useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import { openItem } from './ProjectView'

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
  const w = flat[cursor]
  if (w?.case_id) openItem(w.case_id, w.item_id, true)
}

export function ProblemsPanel() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { data, isLoading } = useWarnings(pid)
  if (isLoading) return <div className="empty">{t('common.loading')}</div>
  if (!data?.length) return <div className="empty">{t('problems.none')}</div>
  return (
    <div role="tree" aria-label={t('panel.problems')} style={{ fontSize: 'var(--fs-panel)' }}>
      {groupWarnings(data).map(([cid, list]) => (
        <div key={cid} role="group">
          <div className="list-row" style={{ cursor: 'default', paddingLeft: 8 }} role="treeitem" aria-expanded>
            <Icon spec={codicon('chevron-down')} />
            <span className="mono">{cid || t('problems.projectLevel')}</span>
            <span className="count">{list.length}</span>
          </div>
          {list.map((w) => (
            <button key={`${w.code}-${w.item_id ?? ''}-${w.field ?? ''}`} type="button" role="treeitem" className="list-row" style={{ paddingLeft: 32 }} disabled={!w.case_id} onClick={() => w.case_id && openItem(w.case_id, w.item_id, true)}>
              <SeverityIcon severity={w.severity} />
              <span>{t(`warning.${w.code}`)}</span>
              <span className="muted">{w.message}</span>
              <span className="muted mono" style={{ marginLeft: 'auto' }}>
                {w.code}
                {w.item_id ? ` · ${w.item_id}` : ''}
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
