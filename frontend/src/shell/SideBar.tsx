import { useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { useLayout } from '../state'
import { Icon, codicon } from '../theme'
import { registry } from './registry'
import { Sash } from './Sash'

export function SideBar() {
  const { t } = useTranslation()
  const layout = useLayout()
  const start = useRef(layout.sidebarWidth)
  const view = registry.views.find((v) => v.id === layout.activeView) ?? registry.views[0]
  if (!layout.sidebarVisible || !view) return null
  const { component: View, actions: Actions } = view
  return (
    <>
      <aside className="sidebar" style={{ width: layout.sidebarWidth }} aria-label={t(view.title)}>
        <div className="sidebar-header">
          <span>{t(view.title)}</span>
          <div className="sidebar-header-actions">{Actions ? <Actions /> : null}</div>
        </div>
        <div className="sidebar-body">
          <View />
        </div>
        {!view.hideImageSection && registry.imageSection.length > 0 ? (
          <section className="sidebar-section" aria-label={t('view.image')}>
            <button
              type="button"
              className="sidebar-section-toggle"
              aria-expanded={layout.imageSectionOpen}
              onClick={() => layout.toggle('imageSectionOpen')}
            >
              <Icon spec={codicon(layout.imageSectionOpen ? 'chevron-down' : 'chevron-right')} />
              {t('view.image')}
            </button>
            {layout.imageSectionOpen
              ? registry.imageSection.map(({ id, component: C }) => <C key={id} />)
              : null}
          </section>
        ) : null}
      </aside>
      <Sash
        direction="v"
        onStart={() => (start.current = layout.sidebarWidth)}
        onDrag={(d) => layout.set({ sidebarWidth: Math.min(640, Math.max(200, start.current + d)) })}
      />
    </>
  )
}
