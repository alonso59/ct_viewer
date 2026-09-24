// Dashboard: run views, measurements panel (DB-*, UI-14)
import { createElement, lazy, Suspense } from 'react'

import i18n from '../../i18n'
import { keys, queryClient, type RunSummary } from '../../api'
import { registry, useWorkbench } from '../../shell'
import { codicon } from '../../theme'
import type { RunParams } from './DashboardEditor'
import { DashboardsView } from './DashboardsView'

// ECharts stays out of the initial bundle (FE-05)
const DashboardEditor = lazy(() => import('./DashboardEditor').then((m) => ({ default: m.DashboardEditor })))
// Kept out of the initial chunk too (NFR-07); the panel has no Suspense boundary of its own
const MeasurementsLazy = lazy(() => import('./MeasurementsPanel').then((m) => ({ default: m.MeasurementsPanel })))
const MeasurementsPanel = () => createElement(Suspense, { fallback: null }, createElement(MeasurementsLazy))

export function registerDashboard() {
  registry.view({ id: 'dashboards', title: 'view.dashboards', icon: codicon('graph'), order: 70, component: DashboardsView, hideImageSection: true })
  registry.panelTab({ id: 'measurements', title: 'panel.measurements', order: 10, component: MeasurementsPanel })
  registry.editor<RunParams>({
    type: 'run',
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
