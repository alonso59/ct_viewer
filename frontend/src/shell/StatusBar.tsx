import { useTranslation } from 'react-i18next'

import { registry } from './registry'

/** Status bar (UI-07): items contributed by features and the app. */
export function StatusBar() {
  const { t } = useTranslation()
  const left = registry.statusItems.filter((s) => s.align === 'left')
  const right = registry.statusItems.filter((s) => s.align === 'right')
  return (
    <footer className="statusbar" aria-label={t('shell.statusBar')}>
      {left.map(({ id, component: C }) => (
        <C key={id} />
      ))}
      <div className="statusbar-spacer" />
      {right.map(({ id, component: C }) => (
        <C key={id} />
      ))}
    </footer>
  )
}
