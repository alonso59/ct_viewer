// Run dashboard tab (DASHBOARD.md): views as dockview sub-panels whose arrangement persists per run
// (DB-01), global filters and colour (DB-02/07), linked selection (DB-04), focus requests (DB-09).
import * as Menu from '@radix-ui/react-dropdown-menu'
import { DockviewReact, type DockviewApi, type DockviewReadyEvent, type IDockviewPanelProps } from 'dockview-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import i18n from '../../i18n'
import { useRun } from '../../api'
import { toast, type EditorProps } from '../../shell'
import { Icon, codicon } from '../../theme'
import { openItem } from '../explorer'
import '../../i18n/lazy'
import { RUN_TONE } from '../radiomics'
import { FilterBar } from './FilterBar'
import { useDashboardStore, useRunDashboard } from './store'
import { ItemMenu, PANELS, type PanelId } from './views'
import { usePid } from './views/common'
import './dashboard.css'

export interface RunParams {
  runId: string
}

interface HostParams {
  id: PanelId
  runId: string
}

const THEME = { name: 'rw-db', className: 'dockview-theme-dark dv-rw db-dock', gap: 0 }
const layoutKey = (pid: string, runId: string) => `rw.dashboard.${pid}.${runId}`
const title = (id: PanelId) => i18n.t(`dashboard.view.${id}`)

function ViewHost({ params }: IDockviewPanelProps<HostParams>) {
  const def = PANELS.find((p) => p.id === params.id)
  if (!def) return null
  const C = def.component
  return <C runId={params.runId} />
}

type Position = Parameters<DockviewApi['addPanel']>[0]['position']

function addPanel(api: DockviewApi, runId: string, id: PanelId, position?: Position) {
  return api.addPanel<HostParams>({ id, component: 'view', title: title(id), params: { id, runId }, position })
}

/** Default arrangement: QC views on top, statistics below */
function defaultLayout(api: DockviewApi, runId: string) {
  const at = (referencePanel: PanelId, direction: 'right' | 'below' | 'within'): Position => ({ referencePanel, direction })
  addPanel(api, runId, 'run-overview')
  addPanel(api, runId, 'outliers', at('run-overview', 'within'))
  addPanel(api, runId, 'missing-matrix', at('run-overview', 'within'))
  addPanel(api, runId, 'feature-distribution', at('run-overview', 'right'))
  addPanel(api, runId, 'feature-vs-volume', at('feature-distribution', 'within'))
  addPanel(api, runId, 'correlation', at('feature-distribution', 'within'))
  addPanel(api, runId, 'phase-side-consistency', at('feature-distribution', 'within'))
  addPanel(api, runId, 'embedding', at('run-overview', 'below'))
  addPanel(api, runId, 'analysis', at('feature-distribution', 'below'))
  addPanel(api, runId, 'group-comparison', at('analysis', 'within'))
  addPanel(api, runId, 'association', at('analysis', 'within'))
  addPanel(api, runId, 'balance', at('analysis', 'within'))
  api.getPanel('outliers')?.api.setActive()
  api.getPanel('feature-distribution')?.api.setActive()
  api.getPanel('analysis')?.api.setActive()
}

function showPanel(api: DockviewApi, runId: string, id: PanelId) {
  const p = api.getPanel(id) ?? addPanel(api, runId, id, api.activePanel ? { referencePanel: api.activePanel.id, direction: 'within' } : undefined)
  p.api.setActive()
}

function ViewsMenu({ api, runId }: { api: DockviewApi | null; runId: string }) {
  const { t } = useTranslation()
  const [, bump] = useState(0)
  return (
    <Menu.Root modal={false} onOpenChange={() => bump((n) => n + 1)}>
      <Menu.Trigger className="btn btn-sm" disabled={!api}>
        <Icon spec={codicon('layout')} />
        {t('dashboard.views')}
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="overlay menu" sideOffset={4} align="end">
          {PANELS.map((p) => (
            <Menu.Item key={p.id} className="menu-item" onSelect={() => api && showPanel(api, runId, p.id)}>
              <Icon spec={codicon(api?.getPanel(p.id) ? 'check' : 'blank')} />
              {t(`dashboard.view.${p.id}`)}
            </Menu.Item>
          ))}
          <Menu.Separator className="menu-sep" />
          <Menu.Item
            className="menu-item"
            onSelect={() => {
              if (!api) return
              api.clear()
              defaultLayout(api, runId)
            }}
          >
            <Icon spec={codicon('discard')} />
            {t('dashboard.resetLayout')}
          </Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}

function SelectionChip({ runId }: { runId: string }) {
  const { t } = useTranslation()
  const selection = useRunDashboard(runId).selection
  const select = useDashboardStore((s) => s.select)
  if (!selection.length) return null
  // The Explorer has no item-id filter yet: copy the ids and open the first item
  const send = () => {
    const first = selection[0] ?? ''
    const done = () => toast({ message: t('dashboard.selection.sent', { count: selection.length }), tone: 'ok' })
    if (navigator.clipboard) navigator.clipboard.writeText(selection.join('\n')).then(done, done)
    else done()
    openItem(first.split('.')[0] ?? '', first, true)
  }
  return (
    <span className="db-chip" data-active="true">
      <span>{t('dashboard.selection.count', { count: selection.length })}</span>
      <button type="button" className="btn btn-sm" onClick={send} title={t('dashboard.selection.sendHint')}>
        <Icon spec={codicon('list-filter')} />
        {t('dashboard.selection.send')}
      </button>
      <button type="button" className="icon-btn" aria-label={t('dashboard.selection.clear')} onClick={() => select(runId, [])}>
        <Icon spec={codicon('close')} />
      </button>
    </span>
  )
}

export function DashboardEditor({ params }: EditorProps<RunParams>) {
  const { t } = useTranslation()
  const pid = usePid()
  const runId = params.runId
  const run = useRun(pid, runId)
  const [api, setApi] = useState<DockviewApi | null>(null)
  const focus = useRunDashboard(runId).focus
  const seen = useRef(0)

  const onReady = (e: DockviewReadyEvent) => {
    setApi(e.api)
    let restored = false
    try {
      const saved = localStorage.getItem(layoutKey(pid, runId))
      if (saved) {
        e.api.fromJSON(JSON.parse(saved))
        restored = e.api.panels.length > 0
      }
    } catch {
      e.api.clear()
    }
    if (!restored) defaultLayout(e.api, runId)
    e.api.onDidLayoutChange(() => {
      try {
        localStorage.setItem(layoutKey(pid, runId), JSON.stringify(e.api.toJSON()))
      } catch {
        // storage unavailable: the arrangement is session-only
      }
    })
  }

  // DB-09: show the requested view (the view component applies the params)
  useEffect(() => {
    if (!api || !focus || focus.nonce === seen.current) return
    seen.current = focus.nonce
    showPanel(api, runId, focus.view)
  }, [api, focus, runId])

  if (run.isLoading) return <div className="empty">{t('common.loading')}</div>
  if (!run.data) return <div className="error-card">{t('common.error')}</div>
  const r = run.data
  return (
    <div className="page db">
      <div className="db-top">
        <Icon spec={codicon('graph')} />
        <strong>{r.name}</strong>
        <span className="badge" data-tone={RUN_TONE[r.status]}>{t(`runStatus.${r.status}`)}</span>
        {r.engine ? <span className="muted mono db-meta">{t('dashboard.meta', { engine: `${r.engine.name} ${r.engine.version}`, hash: r.profile_hash.replace(/^sha256:/, '').slice(0, 12) })}</span> : null}
        <span style={{ flex: 1 }} />
        <ViewsMenu api={api} runId={runId} />
      </div>
      <FilterBar runId={runId} labels={r.selection.labels} trailing={<SelectionChip runId={runId} />} />
      <div className="db-dock-host">
        <DockviewReact theme={THEME} components={{ view: ViewHost }} onReady={onReady} />
      </div>
      <ItemMenu />
    </div>
  )
}
