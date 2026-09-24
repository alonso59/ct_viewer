// Explorer: case tree, filters, quick open, problems (UI-05, UI-08, UI-09)
import { api, keys, queryClient, type CaseFilter, type CaseSummary, type QCWarning } from '../../api'
import { registry, useWorkbench } from '../../shell'
import { useLayout, useViewerSync } from '../../state'
import { codicon } from '../../theme'
import { nextProblem, ProblemsPanel, useProblemsBadge } from './ProblemsPanel'
import { openItem, ProjectView, ProjectViewActions } from './ProjectView'
import { QuickOpenCases } from './QuickOpen'
import { SearchView } from './SearchView'
import { activeFilterCount, useExplorer } from './store'

export { openItem } from './ProjectView'
export { itemLabel } from './itemLabel'
export { explorerSelection, type DroppedCriterion, type ExplorerSelection } from './selection'

/** Read-only view of the current Explorer filter (RAD-05 "Use the current Explorer filter") */
export const useExplorerFilter = (): Readonly<CaseFilter> => useExplorer((s) => s.filter)

/** DB-04: filter the Explorer to these items (and their cases) and show the Project view */
export function showItemsInExplorer(itemIds: string[]) {
  useExplorer.getState().setItemIds(itemIds.length ? itemIds : null)
  useLayout.getState().showView('project')
}

function stepCase(delta: 1 | -1) {
  const order = useExplorer.getState().order
  if (!order.length) return
  const cur = useViewerSync.getState().activeCaseId
  const i = cur ? order.indexOf(cur) : -1
  const next = order[Math.max(0, Math.min(order.length - 1, i + delta))]
  if (next && next !== cur) openItem(next, null, true)
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
  registry.panelTab({ id: 'problems', title: 'panel.problems', order: 20, component: ProblemsPanel, useBadge: useProblemsBadge })
  registry.quickOpenProvider({ id: 'cases', order: 10, component: QuickOpenCases })
  registry.command({ id: 'explorer.nextCase', title: 'cmd.nextCase', category: 'cat.navigate', keybinding: 'alt+down', run: () => stepCase(1) })
  registry.command({ id: 'explorer.prevCase', title: 'cmd.prevCase', category: 'cat.navigate', keybinding: 'alt+up', run: () => stepCase(-1) })
  registry.command({
    id: 'explorer.nextProblem',
    title: 'cmd.nextProblem',
    category: 'cat.navigate',
    keybinding: 'f8',
    run: () => {
      const pid = useWorkbench.getState().pid
      if (!pid) return
      void queryClient.fetchQuery({ queryKey: keys.warnings(pid), queryFn: () => api.listWarnings(pid) }).then((ws: QCWarning[]) => nextProblem(ws))
    },
  })
  registry.command({
    id: 'explorer.clearFilters',
    title: 'explorer.clearFilters',
    category: 'cat.project',
    run: () => useExplorer.getState().clearFilter(),
  })
}

export type { CaseSummary }
