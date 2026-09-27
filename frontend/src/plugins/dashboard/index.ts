// Dashboard: run views, measurements panel (DB-*, UI-14)
import { createElement, lazy, Suspense } from 'react'

import i18n from '../../i18n'
import { api, fetchSettled, keys, queryClient, useFeatures, useRuns, type RunStatus, type RunSummary } from '../../api'
import { openEditor, registry, toast, useWorkbench } from '../../shell'
import { useViewerSync } from '../../state'
import { codicon } from '../../theme'
import { revealView, type FrontendPlugin } from '../host'
import type { RunParams } from './DashboardEditor'
import { DashboardsView } from './DashboardsView'

// ECharts stays out of the initial bundle (FE-05)
const DashboardEditor = lazy(() => import('./DashboardEditor').then((m) => ({ default: m.DashboardEditor })))
// Kept out of the initial chunk too (NFR-07); the panel has no Suspense boundary of its own
const MeasurementsLazy = lazy(() => import('./MeasurementsPanel').then((m) => ({ default: m.MeasurementsPanel })))
const MeasurementsPanel = () => createElement(Suspense, { fallback: null }, createElement(MeasurementsLazy))

export const plugin: FrontendPlugin = {
  id: 'dashboard',
  activate: () => registerDashboard(),
  open: () => revealView('dashboards'),
}

const DONE: RunStatus[] = ['completed', 'completed_with_errors']

/** AUD-A1-06: open the dashboard of the newest completed run */
async function openLatest() {
  const pid = useWorkbench.getState().pid
  if (!pid) return
  const runs = await fetchSettled(queryClient, keys.runs(pid), () => api.listRuns(pid))
  const latest = runs.filter((r) => DONE.includes(r.status)).sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
  if (latest) openEditor('run', { runId: latest.run_id })
  else toast({ message: i18n.t('dashboard.noRuns') })
}

/** AUD-A3-01: the active item has feature rows in the run the Measurements panel shows first */
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
  registry.editor<RunParams>({
    type: 'run',
    writes: true,
    component: DashboardEditor,
    id: (p) => `run:${p.runId}`,
    title: (p) => {
      const pid = useWorkbench.getState().pid ?? ''
      const run = queryClient.getQueryData<RunSummary[]>(keys.runs(pid))?.find((r) => r.run_id === p.runId)
      return run?.name ?? i18n.t('dashboard.tabTitle')
    },
    icon: () => codicon('graph'),
    path: (pid, p) => `/p/${pid}/run/${p.runId}`,
    match: (path) => {
      const m = /^\/run\/([^/]+)$/.exec(path)
      return m?.[1] ? { runId: m[1] } : null
    },
  })
}
