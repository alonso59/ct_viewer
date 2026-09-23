import { useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { useLayout } from '../state'
import { registry } from './registry'
import { Sash } from './Sash'

/** Optional right inspector (UI-01), closed by default; sections come from features. */
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
        {registry.inspectorSections.map(({ id, title, component: C }) => (
          <section key={id} className="inspector-section">
            <div className="section-title">{t(title)}</div>
            <div className="inspector-body">
              <C />
            </div>
          </section>
        ))}
      </aside>
    </>
  )
}
