import { useEffect, useRef, type KeyboardEvent } from 'react'
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
    <button type="button" role="tab" id={`panel-tab-${p.id}`} aria-controls="panel-body" tabIndex={selected ? 0 : -1} className="panel-tab" aria-selected={selected} onClick={onSelect}>
      {t(p.title)}
      {badge ? <span className="count">{badge}</span> : null}
    </button>
  )
}

/** Every panel tab with a `useHasContent` hook reports to the layout whether it has
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
  useEffect(() => {
    useLayout.getState().setPanelContent(p.id, has)
  }, [p.id, has])
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
  // one Tab stop on the selected tab; the arrows select the next one (WAI-ARIA tabs)
  const tabs = registry.panelTabs
  const onTabKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const at = tabs.findIndex((p) => p.id === active?.id)
    const to = e.key === 'ArrowRight' ? at + 1 : e.key === 'ArrowLeft' ? at - 1 : e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : null
    const next = to === null ? undefined : tabs[(to + tabs.length) % tabs.length]
    if (!next) return
    e.preventDefault()
    layout.showPanelTab(next.id)
    document.getElementById(`panel-tab-${next.id}`)?.focus()
  }
  return (
    <>
      <Sash
        direction="h"
        label={t('shell.resizePanel')}
        value={height}
        min={100}
        max={window.innerHeight - 200}
        onStart={() => (start.current = height)}
        onDrag={(d) => layout.set({ panelHeight: Math.min(window.innerHeight - 200, Math.max(100, start.current - d)) })}
        onReset={() => layout.resetSize('panelHeight')}
      />
      <section className="panel" style={{ height }} aria-label={t('shell.panel')}>
        <div className="panel-tabs">
          {/* the tablist holds only tabs; the panel's own buttons sit beside it */}
          <div className="panel-tablist" role="tablist" aria-label={t('shell.panel')} onKeyDown={onTabKey}>
            {tabs.map((p) => (
              <Tab key={p.id} p={p} selected={p.id === active?.id} onSelect={() => layout.showPanelTab(p.id)} />
            ))}
          </div>
          <div className="panel-actions">
            <IconButton
              icon={codicon(maxed ? 'chevron-down' : 'chevron-up')}
              label={t(maxed ? 'shell.restorePanel' : 'shell.maximizePanel')}
              onClick={() => layout.set({ panelHeight: maxed ? null : window.innerHeight - 240 })}
            />
            <IconButton icon={codicon('close')} label={t('shell.closePanel')} onClick={() => layout.set({ panelVisible: false })} />
          </div>
        </div>
        <div className="panel-body" id="panel-body" role="tabpanel" aria-labelledby={active ? `panel-tab-${active.id}` : undefined}>{Body ? <Body /> : null}</div>
      </section>
    </>
  )
}
