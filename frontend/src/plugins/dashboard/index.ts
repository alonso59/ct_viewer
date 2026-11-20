import { createElement, lazy, Suspense, type ComponentProps } from 'react'

import i18n from '../../i18n'
import { api, fetchSettled, keys, queryClient, useFeatures, useRuns, type RunStatus, type TableSummary } from '../../api'
import { openEditor, registry, toast, useWorkbench, type EditorProps } from '../../shell'
import { useViewerSync } from '../../state'
import { codicon } from '../../theme'
import { revealView, type FrontendPlugin } from '../host'
import type { TableParams } from './DashboardEditor'
import { DashboardsView } from './DashboardsView'

// ECharts stays out of the initial bundle
const DashboardEditor = lazy(() => import('./DashboardEditor').then((m) => ({ default: m.DashboardEditor })))
// Kept out of the initial chunk too; the panel has no Suspense boundary of its own
const MeasurementsLazy = lazy(() => import('./MeasurementsPanel').then((m) => ({ default: m.MeasurementsPanel })))
const MeasurementsPanel = () => createElement(Suspense, { fallback: null }, createElement(MeasurementsLazy))

// A column summary for other views; the chart loads on first use
const ValueSummaryLazy = lazy(() => import('./ValueSummary').then((m) => ({ default: m.ValueSummary })))
export const ValueSummary = (props: ComponentProps<typeof ValueSummaryLazy>) =>
  createElement(Suspense, { fallback: null }, createElement(ValueSummaryLazy, props))

const ContingencyMapLazy = lazy(() => import('./ContingencyMap').then((m) => ({ default: m.ContingencyMap })))
export const ContingencyMap = (props: ComponentProps<typeof ContingencyMapLazy>) =>
  createElement(Suspense, { fallback: null }, createElement(ContingencyMapLazy, props))

const EventTimelineLazy = lazy(() => import('./EventTimeline').then((m) => ({ default: m.EventTimeline })))
export const EventTimeline = (props: ComponentProps<typeof EventTimelineLazy>) =>
  createElement(Suspense, { fallback: null }, createElement(EventTimelineLazy, props))

export const plugin: FrontendPlugin = {
  id: 'dashboard',
  activate: () => registerDashboard(),
  open: () => revealView('dashboards'),
}

const DONE: RunStatus[] = ['completed', 'completed_with_errors']

/** Open the dashboard of the newest finished analysis table */
async function openLatest() {
  const pid = useWorkbench.getState().pid
  if (!pid) return
  const tables = await fetchSettled(queryClient, keys.tables(pid), () => api.listTables(pid))
  const latest = tables.filter((t) => DONE.includes(t.status as RunStatus)).sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
  if (latest) openEditor('table', { tableId: latest.table_id })
  else toast({ message: i18n.t('dashboard.noRuns') })
}

const tableTitle = (tableId: string) => {
  const pid = useWorkbench.getState().pid ?? ''
  const table = queryClient.getQueryData<TableSummary[]>(keys.tables(pid))?.find((t) => t.table_id === tableId)
  return table?.title ?? i18n.t('dashboard.tabTitle')
}

/** Tabs and links of the radiomics-run dashboards (before analysis tables) open the same tab */
interface RunParams {
  runId: string
}
const RunAlias = ({ params, ...rest }: EditorProps<RunParams>) => createElement(DashboardEditor, { ...rest, params: { tableId: params.runId } })

/** The active item has feature rows in the run the Measurements panel shows first */
function useMeasurementsContent() {
  const pid = useWorkbench((s) => s.pid) ?? ''
  const iid = useViewerSync((s) => s.activeItemId)
  const rid = (useRuns(pid).data ?? []).find((r) => DONE.includes(r.status))?.run_id ?? null
  return (useFeatures(pid, rid, iid).data?.length ?? 0) > 0
}

export function registerDashboard() {
  registry.view({ id: 'dashboards', writes: true, title: 'view.dashboards', icon: codicon('graph'), order: 70, component: DashboardsView, hideImageSection: true })
  registry.command({ id: 'dashboard.openLatest', writes: true, title: 'cmd.openLatestDashboard', category: 'cat.navigate', keywords: ['kw.radiomics', 'kw.features'], menuGroup: 3, run: () => void openLatest() })
  registry.panelTab({ id: 'measurements', title: 'panel.measurements', order: 10, component: MeasurementsPanel, useHasContent: useMeasurementsContent })
  registry.editor<TableParams>({
    type: 'table',
    writes: true,
    component: DashboardEditor,
    id: (p) => `table:${p.tableId}`,
    title: (p) => tableTitle(p.tableId),
    icon: () => codicon('graph'),
    path: (pid, p) => `/p/${pid}/table/${p.tableId}`,
    match: (path) => {
      const m = /^\/table\/([^/]+)$/.exec(path)
      return m?.[1] ? { tableId: m[1] } : null
    },
  })
  registry.editor<RunParams>({
    type: 'run',
    writes: true,
    component: RunAlias,
    id: (p) => `table:${p.runId}`,
    title: (p) => tableTitle(p.runId),
    icon: () => codicon('graph'),
    path: (pid, p) => `/p/${pid}/table/${p.runId}`,
    match: (path) => {
      const m = /^\/run\/([^/]+)$/.exec(path)
      return m?.[1] ? { runId: m[1] } : null
    },
  })
}
