// Dashboard tab of an analysis table (a radiomics run or a task's table): views as dockview
// sub-panels whose arrangement persists per table.
import * as Menu from '@radix-ui/react-dropdown-menu'
import { DockviewReact, type DockviewApi, type DockviewReadyEvent, type IDockviewPanelProps } from 'dockview-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import i18n from '../../i18n'
import { api, useRun, useTable, type RunStatus } from '../../api'
import { RunStatusBadge, ProblemCard } from '../../lib'
import { toast, type EditorProps } from '../../shell'
import { Icon, codicon } from '../../theme'
import { showItemsInExplorer } from '../../features/explorer'
import '../../i18n/lazy'
import { FilterBar } from './FilterBar'
import { useDashboardStore, useTableDashboard } from './store'
import { ItemMenu, PANELS, type PanelId } from './views'
import { usePid } from './views/common'
import './dashboard.css'

export interface TableParams {
  tableId: string
}

interface HostParams {
  id: PanelId
  tableId: string
}

const THEME = { name: 'rw-db', className: 'dockview-theme-dark dv-rw db-dock', gap: 0 }
const layoutKey = (pid: string, tableId: string) => `rw.dashboard.${pid}.${tableId}`
const title = (id: PanelId) => i18n.t(`dashboard.view.${id}`)

function ViewHost({ params }: IDockviewPanelProps<HostParams>) {
  const def = PANELS.find((p) => p.id === params.id)
  if (!def) return null
  const C = def.component
  return <C tableId={params.tableId} />
}

type Position = Parameters<DockviewApi['addPanel']>[0]['position']

function addPanel(dock: DockviewApi, tableId: string, id: PanelId, position?: Position) {
  return dock.addPanel<HostParams>({ id, component: 'view', title: title(id), params: { id, tableId }, position })
}

/** Size views need the table's volume column */
const panelsFor = (hasVolume: boolean) => PANELS.filter((p) => hasVolume || p.id !== 'feature-vs-volume')

/** Default arrangement: QC views on top, statistics below */
function defaultLayout(dock: DockviewApi, tableId: string, hasVolume: boolean) {
  const at = (referencePanel: PanelId, direction: 'right' | 'below' | 'within'): Position => ({ referencePanel, direction })
  addPanel(dock, tableId, 'run-overview')
  addPanel(dock, tableId, 'outliers', at('run-overview', 'within'))
  addPanel(dock, tableId, 'missing-matrix', at('run-overview', 'within'))
  addPanel(dock, tableId, 'feature-distribution', at('run-overview', 'right'))
  if (hasVolume) addPanel(dock, tableId, 'feature-vs-volume', at('feature-distribution', 'within'))
  addPanel(dock, tableId, 'correlation', at('feature-distribution', 'within'))
  addPanel(dock, tableId, 'phase-side-consistency', at('feature-distribution', 'within'))
  addPanel(dock, tableId, 'embedding', at('run-overview', 'below'))
  addPanel(dock, tableId, 'analysis', at('feature-distribution', 'below'))
  addPanel(dock, tableId, 'group-comparison', at('analysis', 'within'))
  addPanel(dock, tableId, 'association', at('analysis', 'within'))
  addPanel(dock, tableId, 'balance', at('analysis', 'within'))
  dock.getPanel('outliers')?.api.setActive()
  dock.getPanel('feature-distribution')?.api.setActive()
  dock.getPanel('analysis')?.api.setActive()
}

function showPanel(dock: DockviewApi, tableId: string, id: PanelId) {
  const p = dock.getPanel(id) ?? addPanel(dock, tableId, id, dock.activePanel ? { referencePanel: dock.activePanel.id, direction: 'within' } : undefined)
  p.api.setActive()
}

function ViewsMenu({ dock, tableId, hasVolume }: { dock: DockviewApi | null; tableId: string; hasVolume: boolean }) {
  const { t } = useTranslation()
  const [, bump] = useState(0)
  return (
    <Menu.Root modal={false} onOpenChange={() => bump((n) => n + 1)}>
      <Menu.Trigger className="btn btn-sm" disabled={!dock}>
        <Icon spec={codicon('layout')} />
        {t('dashboard.views')}
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="overlay menu" sideOffset={4} align="end">
          {panelsFor(hasVolume).map((p) => (
            <Menu.Item key={p.id} className="menu-item" onSelect={() => dock && showPanel(dock, tableId, p.id)}>
              <Icon spec={codicon(dock?.getPanel(p.id) ? 'check' : 'blank')} />
              {t(`dashboard.view.${p.id}`)}
            </Menu.Item>
          ))}
          <Menu.Separator className="menu-sep" />
          <Menu.Item
            className="menu-item"
            onSelect={() => {
              if (!dock) return
              dock.clear()
              defaultLayout(dock, tableId, hasVolume)
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

function SelectionChip({ tableId }: { tableId: string }) {
  const { t } = useTranslation()
  const selection = useTableDashboard(tableId).selection
  const select = useDashboardStore((s) => s.select)
  if (!selection.length) return null
  const send = () => {
    showItemsInExplorer(selection)
    toast({ message: t('dashboard.selection.sent', { count: selection.length }), tone: 'ok' })
  }
  return (
    <span className="db-chip" data-active="true">
      <span>{t('dashboard.selection.count', { count: selection.length })}</span>
      <button type="button" className="btn btn-sm" onClick={send} title={t('dashboard.selection.sendHint')}>
        <Icon spec={codicon('list-filter')} />
        {t('dashboard.selection.send')}
      </button>
      <button type="button" className="icon-btn" aria-label={t('dashboard.selection.clear')} onClick={() => select(tableId, [])}>
        <Icon spec={codicon('close')} />
      </button>
    </span>
  )
}

export function DashboardEditor({ params }: EditorProps<TableParams>) {
  const { t } = useTranslation()
  const pid = usePid()
  const tableId = params.tableId
  const table = useTable(pid, tableId)
  // a radiomics run also names its engine and settings
  const run = useRun(pid, table.data?.kind === 'radiomics' ? tableId : null)
  const hasVolume = !!table.data?.roles?.volume
  const [dock, setDock] = useState<DockviewApi | null>(null)
  const focus = useTableDashboard(tableId).focus
  const seen = useRef(0)

  const onReady = (e: DockviewReadyEvent) => {
    setDock(e.api)
    let restored = false
    try {
      const saved = localStorage.getItem(layoutKey(pid, tableId))
      if (saved) {
        e.api.fromJSON(JSON.parse(saved))
        restored = e.api.panels.length > 0
      }
    } catch {
      e.api.clear()
    }
    if (!restored) defaultLayout(e.api, tableId, hasVolume)
    e.api.onDidLayoutChange(() => {
      try {
        localStorage.setItem(layoutKey(pid, tableId), JSON.stringify(e.api.toJSON()))
      } catch {
        // storage unavailable: the arrangement is session-only
      }
    })
  }

  // Show the requested view; the view component applies the params
  useEffect(() => {
    if (!dock || !focus || focus.nonce === seen.current) return
    seen.current = focus.nonce
    showPanel(dock, tableId, focus.view)
  }, [dock, focus, tableId])

  if (table.isLoading) return <div className="empty">{t('common.loading')}</div>
  if (!table.data) return <ProblemCard error={table.error} onRetry={() => void table.refetch()} />
  const tb = table.data
  const r = run.data
  return (
    <div className="page db">
      <div className="db-top">
        <Icon spec={codicon('graph')} />
        <strong>{tb.title}</strong>
        <RunStatusBadge status={tb.status as RunStatus} />
        {r?.engine ? (
          <span className="muted mono db-meta">{t('dashboard.meta', { engine: `${r.engine.name} ${r.engine.version}`, hash: r.profile_hash.replace(/^sha256:/, '').slice(0, 12) })}</span>
        ) : tb.grain === 'instance' ? (
          <span className="muted db-meta">{t('dashboard.instanceMeta', { count: tb.counts?.observations ?? 0, items: tb.counts?.items ?? 0, name: tb.instance_name ?? '' })}</span>
        ) : null}
        <span style={{ flex: 1 }} />
        <a className="btn btn-sm" href={api.tableExportUrl(pid, tableId, 'csv', 'wide')} download title={t('dashboard.downloadHint')}>
          <Icon spec={codicon('cloud-download')} />
          {t('dashboard.download')}
        </a>
        <ViewsMenu dock={dock} tableId={tableId} hasVolume={hasVolume} />
      </div>
      <FilterBar tableId={tableId} labels={tb.labels ?? []} trailing={<SelectionChip tableId={tableId} />} />
      <div className="db-dock-host">
        <DockviewReact theme={THEME} components={{ view: ViewHost }} onReady={onReady} />
      </div>
      <ItemMenu />
    </div>
  )
}
