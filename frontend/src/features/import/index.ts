// Import wizard (IMP-01..05)
import { registry, useWorkbench } from '../../shell'

export { ImportWizard, useImportWizard } from './ImportWizard'
import { useImportWizard } from './ImportWizard'

export function registerImport() {
  registry.command({
    id: 'import.open',
    title: 'import.title',
    category: 'cat.project',
    menu: 'file',
    menuGroup: 2,
    enabled: () => useWorkbench.getState().pid !== null,
    run: () => {
      const pid = useWorkbench.getState().pid
      if (pid) useImportWizard.getState().open(pid)
    },
  })
}
