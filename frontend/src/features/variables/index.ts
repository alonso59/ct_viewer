// Study variables (VARIABLES.md): catalog, overrides, derived and external variables (VAR-*)
import { registry, useWorkbench } from '../../shell'
import { useLayout } from '../../state'
import { codicon } from '../../theme'
import { useVariablesUi } from './store'
import { VariablesActions, VariablesView } from './VariablesView'

export function registerVariables() {
  registry.view({
    id: 'variables',
    title: 'view.variables',
    icon: codicon('symbol-variable'),
    order: 85,
    component: VariablesView,
    actions: VariablesActions,
    hideImageSection: true,
  })
  const hasProject = () => useWorkbench.getState().pid !== null
  const openDialog = (d: 'derived' | 'external') => {
    useLayout.getState().showView('variables')
    useVariablesUi.getState().openDialog(d)
  }
  registry.command({ id: 'variables.newDerived', title: 'variables.newDerived', category: 'cat.project', menu: 'project', menuGroup: 3, enabled: hasProject, run: () => openDialog('derived') })
  registry.command({ id: 'variables.importTable', title: 'variables.importTable', category: 'cat.project', menu: 'project', menuGroup: 3, enabled: hasProject, run: () => openDialog('external') })
}
