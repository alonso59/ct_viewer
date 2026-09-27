import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { IconButton } from '../lib'
import { panelAutoHeight, useLayout } from '../state'
import { codicon } from '../theme'
import { registry, type PanelTabContribution } from './registry'
import { Sash } from './Sash'

function Tab({ p, selected, onSelect }: { p: PanelTabContribution; selected: boolean; onSelect: () => void }) {
  const { t } = useTranslation()
  const badge = p.useBadge?.() ?? null
  return (
    <button type="button" role="tab" className="panel-tab" aria-selected={selected} onClick={onSelect}>
      {t(p.title)}
      {badge ? <span className="count">{badge}</span> : null}
    </button>
  )
}

/** AUD-A3-01: every panel tab with a `useHasContent` hook reports to the layout whether it has
 *  content for the active item; a content-first editor (a case tab) opens the panel only then */
export function PanelContentWatch() {
  return (
    <>
      {registry.panelTabs.filter((p) => p.useHasContent).map((p) => <ContentProbe key={p.id} p={p} />)}
    </>
  )
}

function ContentProbe({ p }: { p: PanelTabContribution }) {
  const has = p.useHasContent?.() ?? false
  useEffect(() => useLayout.getState().setPanelContent(p.id, has), [p.id, has])
  return null
}

/** Bottom panel (VS Code): Measurements · Problems · History · Output · Jobs */
export function Panel() {
  const { t } = useTranslation()
  const layout = useLayout()
  const height = layout.panelHeight ?? panelAutoHeight()
  const start = useRef(height)
  if (!layout.panelVisible) return null
  const active = registry.panelTabs.find((p) => p.id === layout.activePanelTab) ?? registry.panelTabs[0]
  const Body = active?.component
  const maxed = height > window.innerHeight * 0.6
  return (
    <>
      <Sash
        direction="h"
        onStart={() => (start.current = height)}
        onDrag={(d) => layout.set({ panelHeight: Math.min(window.innerHeight - 200, Math.max(100, start.current - d)) })}
      />
      <section className="panel" style={{ height }} aria-label={t('shell.panel')}>
        <div className="panel-tabs" role="tablist">
          {registry.panelTabs.map((p) => (
            <Tab key={p.id} p={p} selected={p.id === active?.id} onSelect={() => layout.showPanelTab(p.id)} />
          ))}
          <div className="panel-actions">
            <IconButton
              icon={codicon(maxed ? 'chevron-down' : 'chevron-up')}
              label={t(maxed ? 'shell.restorePanel' : 'shell.maximizePanel')}
              onClick={() => layout.set({ panelHeight: maxed ? null : window.innerHeight - 240 })}
            />
            <IconButton icon={codicon('close')} label={t('shell.closePanel')} onClick={() => layout.set({ panelVisible: false })} />
          </div>
        </div>
        <div className="panel-body" role="tabpanel">{Body ? <Body /> : null}</div>
      </section>
    </>
  )
}
