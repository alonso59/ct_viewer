// Radiomics: schema-driven settings, profiles, runs (RAD-*)
import './i18n'

import i18n from '../../i18n'
import { openEditor, registry } from '../../shell'
import { codicon } from '../../theme'
import { LazySettingsEditor } from './LazySettingsEditor'
import { RadiomicsView } from './RadiomicsView'

export { RUN_TONE } from './runs'

export function registerRadiomics() {
  registry.view({ id: 'radiomics', title: 'view.radiomics', icon: codicon('beaker'), order: 60, component: RadiomicsView, hideImageSection: true })
  registry.editor({
    type: 'radiomics',
    component: LazySettingsEditor,
    id: () => 'radiomics',
    title: () => i18n.t('rad.title'),
    icon: () => codicon('beaker'),
    path: (pid) => `/p/${pid}/radiomics`,
    match: (path) => (path === '/radiomics' ? {} : null),
  })
  registry.command({ id: 'radiomics.new', title: 'radiomics.newRun', category: 'cat.radiomics', menu: 'radiomics', menuGroup: 1, run: () => openEditor('radiomics', {}) })
}
