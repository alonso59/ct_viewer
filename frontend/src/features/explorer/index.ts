// Explorer: case tree, filters, quick open, problems (UI-05, UI-08, UI-09)
import { api, fetchSettled, keys, queryClient, useItem, type CaseFilter, type CaseSummary, type QCWarning } from '../../api'
import i18n from '../../i18n'
import { registry, toast, useWorkbench } from '../../shell'
import { navPosition, useLayout, useNavContext, useViewerSync } from '../../state'
import { codicon } from '../../theme'
import { nextProblem, ProblemsPanel, useProblemsBadge } from './ProblemsPanel'
import { openItem } from './navigate'
import { ProjectView, ProjectViewActions } from './ProjectView'
import { QuickOpenCases } from './QuickOpen'
import { SearchView } from './SearchView'
import { activeFilterCount, useExplorer } from './store'

export { openItem, openInContext, openFromExplorer } from './navigate'
export { itemLabel } from './itemLabel'
export { explorerSelection, type DroppedCriterion, type ExplorerSelection } from './selection'

/** Read-only view of the current Explorer filter (RAD-05 "Use the current Explorer filter") */
export const useExplorerFilter = (): Readonly<CaseFilter> => useExplorer((s) => s.filter)

/** DB-04: filter the Explorer to these items (and their cases) and show the Project view */
export function showItemsInExplorer(itemIds: string[]) {
  useExplorer.getState().setItemIds(itemIds.length ? itemIds : null)
  useLayout.getState().showView('project')
}

/** AUD-A3-01: the active item has QC warnings (the Problems panel then has something for it) */
function useProblemsContent() {
  const pid = useWorkbench((s) => s.pid) ?? ''
  const iid = useViewerSync((s) => s.activeItemId)
  return (useItem(pid, iid).data?.warning_codes.length ?? 0) > 0
}

function stepCase(delta: 1 | -1) {
  const { activeCaseId: cur, activeItemId } = useViewerSync.getState()
  const nav = useNavContext.getState()
  const pos = navPosition(nav, cur, activeItemId)
  if (pos !== null) {
    const next = nav.entries[pos + delta]
    if (!next) {
      toast({ message: i18n.t(delta > 0 ? 'nav.endOf' : 'nav.startOf', { list: nav.label }) })
      return
    }
    nav.setIndex(pos + delta)
    openItem(next.caseId, next.itemId, true)
    return
  }
  const order = useExplorer.getState().order
  if (!order.length) return
  const i = cur ? order.indexOf(cur) : -1
  const next = order[Math.max(0, Math.min(order.length - 1, i + delta))]
  if (next && next !== cur) openItem(next, null, true)
}

/** Go: Next unreviewed case (AUD-A1-04): the next case in Explorer order that is not fully
 *  reviewed (CUR-08 `review_state`), after the active one, wrapping around */
async function nextUnreviewed() {
  const pid = useWorkbench.getState().pid
  if (!pid) return
  const filter = useExplorer.getState().filter
  const cases = await fetchSettled(queryClient, keys.cases(pid, filter), () => api.listCases(pid, filter))
  const cur = useViewerSync.getState().activeCaseId
  const next = pickNextUnreviewed(cases, cur)
  if (!next) {
    toast({ message: i18n.t('nav.allReviewed'), tone: 'ok' })
    return
  }
  useNavContext.getState().clear()
  openItem(next.case_id, null, true)
}

/** Pure part of `nextUnreviewed` (unit-tested) */
export function pickNextUnreviewed(cases: CaseSummary[], current: string | null): CaseSummary | undefined {
  const i = current ? cases.findIndex((c) => c.case_id === current) : -1
  const rest = [...cases.slice(i + 1), ...cases.slice(0, i + 1)]
  return rest.find((c) => c.review_state !== 'reviewed' && c.case_id !== current && !c.excluded)
}

export function registerExplorer() {
  registry.view({
    id: 'project',
    title: 'view.project',
    icon: codicon('files'),
    order: 10,
    component: ProjectView,
    actions: ProjectViewActions,
  })
  registry.view({
    id: 'search',
    title: 'view.search',
    icon: codicon('search'),
    order: 80,
    component: SearchView,
    hideImageSection: true,
    useBadge: () => {
      const f = useExplorer((s) => s.filter)
      return activeFilterCount(f) || null
    },
  })
  registry.panelTab({ id: 'problems', title: 'panel.problems', order: 20, component: ProblemsPanel, useBadge: useProblemsBadge, useHasContent: useProblemsContent })
  registry.quickOpenProvider({ id: 'cases', order: 10, component: QuickOpenCases })
  registry.command({ id: 'explorer.nextCase', title: 'cmd.nextCase', category: 'cat.navigate', keybinding: 'alt+down', menuGroup: 1, run: () => stepCase(1) })
  registry.command({ id: 'explorer.prevCase', title: 'cmd.prevCase', category: 'cat.navigate', keybinding: 'alt+up', menuGroup: 1, run: () => stepCase(-1) })
  registry.command({ id: 'explorer.nextUnreviewed', title: 'cmd.nextUnreviewed', category: 'cat.navigate', keybinding: 'alt+shift+down', keywords: ['kw.review', 'kw.todo'], menuGroup: 1, run: () => void nextUnreviewed() })
  registry.command({
    id: 'explorer.nextProblem',
    title: 'cmd.nextProblem',
    category: 'cat.navigate',
    keybinding: 'f8',
    keywords: ['kw.warning'],
    menuGroup: 1,
    run: () => {
      const pid = useWorkbench.getState().pid
      if (!pid) return
      void fetchSettled(queryClient, keys.warnings(pid), () => api.listWarnings(pid)).then((ws: QCWarning[]) => nextProblem(ws))
    },
  })
  registry.command({ id: 'explorer.clearNavContext', title: 'nav.clear', category: 'cat.navigate', menuGroup: 2, enabled: () => useNavContext.getState().label !== null, run: () => useNavContext.getState().clear() })
  registry.command({
    id: 'explorer.clearFilters',
    title: 'explorer.clearFilters',
    category: 'cat.navigate',
    menuGroup: 2,
    run: () => useExplorer.getState().clearFilter(),
  })
}

export type { CaseSummary }
