// Native phase selection (PHASE.md, ADR-0026): buttons, history, live toasts and the export.
// Core, not a plugin: available whatever plugins are enabled.
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'

import i18n from '../../i18n'
import { api, appendPhaseNow, keys, PHASES, queryClient, ReviewerCancelled, useProjectEvents, type CaseDetail, type Project, type ServerEvent } from '../../api'
import { registry, toast, useWorkbench, toastProblem } from '../../shell'
import { useViewerSync } from '../../state'
import { phaseOptions } from './model'

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
    toastProblem(e, i18n.t('common.error'))
  }
}

/** The scan of the active item, from the cached case detail */
function activeScan() {
  const pid = useWorkbench.getState().pid
  const { activeCaseId, activeItemId } = useViewerSync.getState()
  if (!pid || !activeCaseId || useWorkbench.getState().active?.type !== 'case') return null
  const item = queryClient.getQueryData<CaseDetail>(keys.case(pid, activeCaseId))?.items.find((i) => i.item_id === activeItemId)
  return item ? { pid, item } : null
}

/** AUD-A1-06: "Phase: Set NP" etc. for the active scan (PHS-01, same event as the buttons) */
function setPhase(value: string) {
  const at = activeScan()
  if (!at) return
  appendPhaseNow(queryClient, at.pid, { case_id: at.item.case_id, scan_idx: at.item.scan_idx, value, source: 'manual' }).then(
    () => toast({ message: i18n.t('phaseSel.setTo', { scan: `${at.item.case_id} · ${at.item.scan_idx}`, phase: value }), tone: 'ok' }),
    (e: unknown) => {
      if (!(e instanceof ReviewerCancelled)) toastProblem(e, i18n.t('common.saveFailed'))
    },
  )
}

const vocabulary = () => {
  const pid = useWorkbench.getState().pid
  return phaseOptions(pid ? queryClient.getQueryData<Project>(keys.project(pid))?.phase_vocabulary : undefined)
}

export function registerPhase() {
  for (const p of PHASES)
    registry.command({
      id: `phase.set.${p}`,
      writes: true,
      title: 'cmd.setPhase',
      titleArgs: { phase: p },
      category: 'cat.phase',
      keywords: ['kw.phase'],
      menuGroup: 1,
      enabled: () => activeScan() !== null && vocabulary().includes(p),
      run: () => setPhase(p),
    })
  registry.command({
    id: 'phase.export', writes: true,
    title: 'phaseSel.export',
    category: 'cat.file',
    menuGroup: 5,
    enabled: () => useWorkbench.getState().pid !== null,
    run: () => void writeExport(),
  })
}
