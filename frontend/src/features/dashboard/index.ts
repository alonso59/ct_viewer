// Dashboard: run views, measurements panel (DB-*, UI-14)
import { lazy } from 'react'

import i18n from '../../i18n'
import { keys, queryClient, type RadiomicsRun } from '../../api'
import { registry, useWorkbench } from '../../shell'
import { codicon } from '../../theme'
import type { RunParams } from './DashboardEditor'
import { DashboardsView } from './DashboardsView'
import { MeasurementsPanel } from './MeasurementsPanel'

// ECharts stays out of the initial bundle (FE-05)
const DashboardEditor = lazy(() => import('./DashboardEditor').then((m) => ({ default: m.DashboardEditor })))

export function registerDashboard() {
  registry.view({ id: 'dashboards', title: 'view.dashboards', icon: codicon('graph'), order: 70, component: DashboardsView, hideImageSection: true })
  registry.panelTab({ id: 'measurements', title: 'panel.measurements', order: 10, component: MeasurementsPanel })
  registry.editor<RunParams>({
    type: 'run',
    component: DashboardEditor,
    id: (p) => `run:${p.runId}`,
    title: (p) => {
      const pid = useWorkbench.getState().pid ?? ''
      const run = queryClient.getQueryData<RadiomicsRun[]>(keys.runs(pid))?.find((r) => r.run_id === p.runId)
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
