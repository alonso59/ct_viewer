// Import wizard (IMP-01..05)
import { registry, useWorkbench } from '../../shell'

export { FolderBrowser } from './FolderBrowser'
export { ImportWizard } from './LazyImportWizard'
export { useImportWizard, type WizardPrefill } from './store'
export { DerivedRootDialog } from './DerivedRootDialog'
import { useImportWizard } from './store'

export function registerImport() {
  registry.command({
    id: 'import.open', writes: true,
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
