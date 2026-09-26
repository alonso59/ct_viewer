// Radiomics: schema-driven settings, profiles, runs (RAD-*)

import i18n from '../../i18n'
import { openEditor, registry } from '../../shell'
import { codicon } from '../../theme'
import { revealView, type FrontendPlugin } from '../host'
import { LazySettingsEditor } from './LazySettingsEditor'
import { RadiomicsView } from './RadiomicsView'

export { RUN_TONE } from './runs'

export const plugin: FrontendPlugin = {
  id: 'radiomics',
  activate: () => registerRadiomics(),
  open: () => revealView('radiomics'),
}

export function registerRadiomics() {
  registry.view({ id: 'radiomics', writes: true, title: 'view.radiomics', icon: codicon('beaker'), order: 60, component: RadiomicsView, hideImageSection: true })
  registry.editor({
    type: 'radiomics',
    writes: true,
    component: LazySettingsEditor,
    id: () => 'radiomics',
    title: () => i18n.t('rad.title'),
    icon: () => codicon('beaker'),
    path: (pid) => `/p/${pid}/radiomics`,
    match: (path) => (path === '/radiomics' ? {} : null),
  })
  registry.command({ id: 'radiomics.new', writes: true, title: 'radiomics.newRun', category: 'cat.tasks', keywords: ['kw.features'], menuGroup: 2, run: () => openEditor('radiomics', {}) })
}
