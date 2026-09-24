// Curation: decisions, history, correction queue, live sync (CUR-*)
import { createElement, lazy, Suspense, useCallback, type ComponentType } from 'react'
import { useTranslation } from 'react-i18next'

import i18n from '../../i18n'
import { api, keys, ProblemError, queryClient, useProjectEvents, type CurationStateRow, type CurationStatus, type ServerEvent } from '../../api'
import { registry, toast, useWorkbench, openEditor } from '../../shell'
import { useViewerSync } from '../../state'
import { codicon } from '../../theme'
import { openItem } from '../../features/explorer'
import { revealView, type FrontendPlugin } from '../host'
import { submitDecision, useDraft } from './decision'
import { statusOf } from './model'

// Curation UI stays out of the initial bundle (FE-05, NFR-07); shortcuts only need ./decision.
// Editors render inside the editor area's Suspense; views and panel tabs get their own boundary.
const QueueEditor = lazy(() => import('./QueueEditor').then((m) => ({ default: m.QueueEditor })))
const suspended = (C: ComponentType) => () => createElement(Suspense, { fallback: null }, createElement(C))
const CurationView = suspended(lazy(() => import('./CurationView').then((m) => ({ default: m.CurationView }))))
const InspectorCuration = suspended(lazy(() => import('./CurationForm').then((m) => ({ default: m.InspectorCuration }))))
const HistoryView = suspended(lazy(() => import('./History').then((m) => ({ default: m.HistoryView }))))
const HistoryPanel = suspended(lazy(() => import('./History').then((m) => ({ default: m.HistoryPanel }))))

/** Mount once in the workbench: shows "updated by" toasts for other reviewers' events (CUR-11). */
export function useCurationRuntime(pid: string) {
  const { t } = useTranslation()
  const onEvent = useCallback(
    (e: ServerEvent) => {
      if (e.event !== 'curation.appended' || e.data.session_id === api.sessionId) return
      toast({
        message: t('curation.updatedBy', { id: e.data.case_id, reviewer: e.data.reviewer, status: t(`status.${e.data.status}`) }),
        action: { label: t('common.open'), run: () => openItem(e.data.case_id, e.data.item_id, true) },
      })
    },
    [t],
  )
  useProjectEvents(pid, onEvent)
}

function currentStatus() {
  const pid = useWorkbench.getState().pid ?? ''
  const { activeItemId, activeCaseId } = useViewerSync.getState()
  const rows = queryClient.getQueryData<CurationStateRow[]>(keys.curationState(pid)) ?? []
  return statusOf(rows, activeItemId, activeCaseId, useDraft.getState().target)
}

/** CUR-10: write curation_state.csv, events.jsonl and phase_proposals.json into `exports/` */
async function writeExports() {
  const pid = useWorkbench.getState().pid
  if (!pid) return
  try {
    const r = await api.curationExports(pid)
    toast({ message: i18n.t('queue.exportsWritten', { dir: r.dir ?? 'exports', files: r.files.join(', ') }), tone: 'ok' })
  } catch (e) {
    toast({ message: e instanceof ProblemError ? (e.detail ?? e.title) : i18n.t('common.error'), tone: 'error' })
  }
}

export const plugin: FrontendPlugin = {
  id: 'curation',
  activate: () => registerCuration(),
  open: () => revealView('curation'),
}

const hasItem = () => useWorkbench.getState().active?.type === 'case' && useViewerSync.getState().activeCaseId !== null

export function registerCuration() {
  registry.view({ id: 'curation', title: 'view.curation', icon: codicon('checklist'), order: 30, component: CurationView })
  registry.view({ id: 'history', title: 'view.history', icon: codicon('history'), order: 50, component: HistoryView })
  registry.inspector({ id: 'curation.form', title: 'inspector.curation', order: 10, component: InspectorCuration })
  registry.panelTab({ id: 'history', title: 'panel.history', order: 30, component: HistoryPanel })
  registry.editor({
    type: 'queue',
    component: QueueEditor,
    id: () => 'queue',
    title: () => i18n.t('queue.title'),
    icon: () => codicon('checklist'),
    path: (pid) => `/p/${pid}/queue`,
    match: (path) => (path === '/queue' ? {} : null),
  })

  const quick: [string, string, CurationStatus][] = [
    ['curation.accept', 'a', 'accepted'],
    ['curation.minor', 'shift+1', 'needs_minor_correction'],
    ['curation.major', 'shift+2', 'needs_major_correction'],
    ['curation.reject', 'x', 'rejected'],
  ]
  for (const [id, key, status] of quick)
    registry.command({
      id,
      title: `status.${status}`,
      category: 'cat.curation',
      keybinding: key,
      when: 'viewer',
      enabled: hasItem,
      run: () => void submitDecision(status),
    })
  registry.command({
    id: 'curation.queue',
    title: 'curation.addToQueue',
    category: 'cat.curation',
    keybinding: 'q',
    when: 'viewer',
    enabled: hasItem,
    // Q flags the item for the queue and keeps its current status (CUR-09)
    run: () => void submitDecision(currentStatus(), { addToQueue: true }),
  })
  registry.command({ id: 'curation.openQueue', title: 'curation.openQueue', category: 'cat.curation', menu: 'project', menuGroup: 2, run: () => openEditor('queue', {}) })
  registry.command({
    id: 'curation.writeExports',
    title: 'queue.writeExports',
    category: 'cat.curation',
    menu: 'project',
    menuGroup: 2,
    enabled: () => useWorkbench.getState().pid !== null,
    run: () => void writeExports(),
  })
  registry.command({
    id: 'curation.clearDraft',
    title: 'curation.clearDraft',
    category: 'cat.curation',
    run: () => useDraft.getState().reset(),
  })
}

