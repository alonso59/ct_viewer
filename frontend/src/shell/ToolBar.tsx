import { useTranslation } from 'react-i18next'

import { registry } from './registry'

/** QuPath-style tool bar (UI-06). Items are contributed by features, e.g. the viewer. */
export function ToolBar() {
  const { t } = useTranslation()
  return (
    <div className="toolbar" role="toolbar" aria-label={t('shell.toolbar')}>
      {registry.tools.map(({ id, component: C }) => (
        <C key={id} />
      ))}
    </div>
  )
}
