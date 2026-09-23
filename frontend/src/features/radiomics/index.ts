// Radiomics: schema-driven settings, profiles, runs (RAD-*)
import i18n from '../../i18n'
import { openEditor, registry } from '../../shell'
import { codicon } from '../../theme'
import { RadiomicsView } from './RadiomicsView'
import { SettingsEditor } from './SettingsEditor'

export { RUN_TONE } from './RadiomicsView'

export function registerRadiomics() {
  registry.view({ id: 'radiomics', title: 'view.radiomics', icon: codicon('beaker'), order: 60, component: RadiomicsView, hideImageSection: true })
  registry.editor({
    type: 'radiomics',
    component: SettingsEditor,
    id: () => 'radiomics',
    title: () => i18n.t('radiomics.tabTitle'),
    icon: () => codicon('beaker'),
    path: (pid) => `/p/${pid}/radiomics`,
    match: (path) => (path === '/radiomics' ? {} : null),
  })
  registry.command({ id: 'radiomics.new', title: 'radiomics.newRun', category: 'cat.radiomics', menu: 'radiomics', menuGroup: 1, run: () => openEditor('radiomics', {}) })
}
