// Native phase selection (PHASE.md, ADR-0026): buttons, history, live toasts and the export.
// Core, not a plugin: available whatever plugins are enabled.
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'

import i18n from '../../i18n'
import { api, ProblemError, useProjectEvents, type ServerEvent } from '../../api'
import { registry, toast, useWorkbench } from '../../shell'

export { PhaseButtons, PhaseHistoryButton } from './PhaseButtons'

/** PHS-05: "updated by" toasts for other browsers' selections; mount once per project */
export function usePhaseRuntime(pid: string) {
  const { t } = useTranslation()
  const onEvent = useCallback(
    (e: ServerEvent) => {
      if (e.event !== 'phase.appended' || e.data.session_id === api.sessionId) return
      toast({ message: t('phaseSel.updatedBy', { scan: `${e.data.case_id} · ${e.data.scan_idx}`, phase: e.data.value, reviewer: e.data.reviewer }) })
    },
    [t],
  )
  useProjectEvents(pid, onEvent)
}

/** PHS-06: `exports/phase_selections.json`, shaped like `phase.json` */
async function writeExport() {
  const pid = useWorkbench.getState().pid
  if (!pid) return
  try {
    const r = await api.exportPhase(pid)
    toast({ message: i18n.t('queue.exportsWritten', { dir: r.dir ?? 'exports', files: r.files.join(', ') }), tone: 'ok' })
  } catch (e) {
    toast({ message: e instanceof ProblemError ? (e.detail ?? e.title) : i18n.t('common.error'), tone: 'error' })
  }
}

export function registerPhase() {
  registry.command({
    id: 'phase.export', writes: true,
    title: 'phaseSel.export',
    category: 'cat.project',
    menu: 'project',
    menuGroup: 2,
    enabled: () => useWorkbench.getState().pid !== null,
    run: () => void writeExport(),
  })
}
