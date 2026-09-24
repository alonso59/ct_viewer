import { useTranslation } from 'react-i18next'

import { Tooltip } from '../lib'
import { useLayout } from '../state'
import { Icon } from '../theme'
import { registry, type ViewContribution } from './registry'

function Item({ v }: { v: ViewContribution }) {
  const { t } = useTranslation()
  const { activeView, sidebarVisible, showView } = useLayout()
  const badge = v.useBadge?.() ?? null
  const current = activeView === v.id && sidebarVisible
  return (
    <Tooltip label={t(v.title)} side="right">
      <button
        type="button"
        className="activitybar-item"
        aria-label={t(v.title)}
        aria-current={current}
        onClick={() => showView(v.id)}
      >
        <Icon spec={v.icon} size={24} />
        {badge ? <span className="activitybar-badge">{badge}</span> : null}
      </button>
    </Tooltip>
  )
}

// Hooks inside items need a stable list; views register once at bootstrap.
export function ActivityBar() {
  const { t } = useTranslation()
  const top = registry.views.filter((v) => v.position !== 'bottom' && registry.allowed(v))
  const bottom = registry.views.filter((v) => v.position === 'bottom' && registry.allowed(v))
  return (
    <nav className="activitybar" aria-label={t('shell.activityBar')}>
      {top.map((v) => (
        <Item key={v.id} v={v} />
      ))}
      <div className="activitybar-spacer" />
      {bottom.map((v) => (
        <Item key={v.id} v={v} />
      ))}
    </nav>
  )
}
