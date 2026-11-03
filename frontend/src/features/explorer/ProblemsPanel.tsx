import { Fragment, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useWarnings, type QCWarning } from '../../api'
import { SeverityIcon, itemName, knownPhase, useRowKeys } from '../../lib'
import { useWorkbench } from '../../shell'
import { Icon, codicon } from '../../theme'
import i18n from '../../i18n'
import { openInContext } from './navigate'

function groupWarnings(ws: QCWarning[]): [string, QCWarning[]][] {
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

/** Opens a warning's item with the Problems list as navigation context */
function openProblem(flat: QCWarning[], i: number) {
  const withCase = flat.filter((w) => w.case_id)
  const at = withCase.indexOf(flat[i] as QCWarning)
  openInContext(i18n.t('panel.problems'), withCase.map((w) => ({ caseId: w.case_id ?? '', itemId: w.item_id })), at, true)
}

const warningKey = (w: QCWarning) => `${w.code}-${w.item_id ?? ''}-${w.field ?? ''}`

/** A tree of one Tab stop: case rows (level 1) open and close with a click, Enter or ←/→; their
 *  warnings (level 2) open the item */
export function ProblemsPanel() {
  const { t } = useTranslation()
  const pid = useWorkbench((s) => s.pid) ?? ''
  const { data, isLoading } = useWarnings(pid)
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set())
  const groups = groupWarnings(data ?? [])
  const rowKeys = useRowKeys(groups.flatMap(([cid, list]) => [`case:${cid}`, ...(closed.has(cid) ? [] : list.map(warningKey))]))
  if (isLoading) return <div className="empty">{t('common.loading')}</div>
  if (!data?.length) return <div className="empty">{t('problems.none')}</div>
  const flat = groups.flatMap(([, list]) => list)
  const toggle = (cid: string) =>
    setClosed((s) => {
      const next = new Set(s)
      if (!next.delete(cid)) next.add(cid)
      return next
    })
  return (
    <div role="tree" aria-label={t('panel.problems')} className="panel-size">
      {groups.map(([cid, list]) => {
        const open = !closed.has(cid)
        const row = rowKeys(`case:${cid}`)
        return (
          <Fragment key={cid}>
            <div
              role="treeitem"
              aria-level={1}
              aria-expanded={open}
              className="list-row"
              style={{ paddingLeft: 8 }}
              onClick={() => toggle(cid)}
              {...row}
              onKeyDown={(e) => {
                if (e.target === e.currentTarget && ((e.key === 'ArrowRight' && !open) || (e.key === 'ArrowLeft' && open))) {
                  e.preventDefault()
                  toggle(cid)
                } else row.onKeyDown(e)
              }}
            >
              <Icon spec={codicon(open ? 'chevron-down' : 'chevron-right')} />
              <span className="mono">{cid || t('problems.projectLevel')}</span>
              <span className="count">{list.length}</span>
            </div>
            {open
              ? list.map((w) => (
                  <div
                    key={warningKey(w)}
                    role="treeitem"
                    aria-level={2}
                    aria-disabled={!w.case_id || undefined}
                    className="list-row"
                    style={{ paddingLeft: 32 }}
                    onClick={() => w.case_id && openProblem(flat, flat.indexOf(w))}
                    {...rowKeys(warningKey(w))}
                  >
                    <SeverityIcon severity={w.severity} />
                    <span>{t(`warning.${w.code}`)}</span>
                    <span className="muted">{w.message}</span>
                    <span className="muted problem-where" title={w.item_id ? `${w.code} · ${w.item_id}` : w.code}>
                      {w.item_id ? itemName(w.item_id, t, knownPhase(pid, w.item_id)) : null}
                    </span>
                  </div>
                ))
              : null}
          </Fragment>
        )
      })}
    </div>
  )
}

export function useProblemsBadge(): number | null {
  const pid = useWorkbench((s) => s.pid) ?? ''
  return useWarnings(pid).data?.length ?? null
}
