import { useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { useLayout } from '../state'
import { Icon, codicon } from '../theme'
import { registry } from './registry'
import { Sash } from './Sash'

export function Inspector() {
  const { t } = useTranslation()
  const layout = useLayout()
  const start = useRef(layout.inspectorWidth)
  if (!layout.inspectorVisible) return null
  return (
    <>
      <Sash
        direction="v"
        onStart={() => (start.current = layout.inspectorWidth)}
        onDrag={(d) => layout.set({ inspectorWidth: Math.min(560, Math.max(240, start.current - d)) })}
      />
      <aside className="inspector" style={{ width: layout.inspectorWidth }} aria-label={t('shell.inspector')}>
        {registry.inspectorSections.filter((s) => registry.allowed(s)).map(({ id, title, component: C }) => {
          const open = !layout.inspectorCollapsed.includes(id)
          return (
            <section key={id} className="inspector-section">
              <button type="button" className="section-title inspector-heading" aria-expanded={open} aria-controls={`inspector-${id}`} onClick={() => layout.set({ inspectorCollapsed: open ? [...layout.inspectorCollapsed, id] : layout.inspectorCollapsed.filter((section) => section !== id) })}>
                <Icon spec={codicon(open ? 'chevron-down' : 'chevron-right')} />{t(title)}
              </button>
              <div id={`inspector-${id}`} className="inspector-body" hidden={!open}>
                <C />
              </div>
            </section>
          )
        })}
      </aside>
    </>
  )
}
