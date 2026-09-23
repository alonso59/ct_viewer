// Curation: decisions, history, correction queue, live sync (CUR-*)
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'

import i18n from '../../i18n'
import { api, keys, queryClient, useProjectEvents, type CurationStateRow, type CurationStatus, type ServerEvent } from '../../api'
import { registry, toast, useWorkbench, openEditor } from '../../shell'
import { useViewerSync } from '../../state'
import { codicon } from '../../theme'
import { openItem } from '../explorer'
import { InspectorCuration, submitDecision, useDraft } from './CurationForm'
import { CurationView } from './CurationView'
import { HistoryPanel, HistoryView } from './History'
import { QueueEditor } from './QueueEditor'

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
  const { activeItemId } = useViewerSync.getState()
  const target = useDraft.getState().target
  const rows = queryClient.getQueryData<CurationStateRow[]>(keys.curationState(pid)) ?? []
  return rows.find((r) => r.item_id === activeItemId && r.target === target)?.status ?? 'not_reviewed'
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
    id: 'curation.clearDraft',
    title: 'curation.clearDraft',
    category: 'cat.curation',
    run: () => useDraft.getState().reset(),
  })
}

