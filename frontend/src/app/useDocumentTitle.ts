// The browser tab says where the user is, e.g. "case_00042 · NP · Full scan — Dataset820 — Radiology
// Workbench". Open mode names no file or folder: source paths may carry patient names.
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { useCase } from '../api'
import { itemName } from '../lib'
import { registry, useWorkbench, type EditorParams } from '../shell'

/** `parts` from the most specific to the least; the app name comes last */
export function useDocumentTitle(...parts: (string | null | undefined)[]) {
  const { t } = useTranslation()
  const title = [...parts, t('app.title')].filter(Boolean).join(' — ')
  useEffect(() => {
    document.title = title
  }, [title])
}

/** A page outside a project: the app name, after the translated `titleKey` (Open mode) */
export function PageTitle({ titleKey }: { titleKey?: string }) {
  const { t } = useTranslation()
  useDocumentTitle(titleKey ? t(titleKey) : null)
  return null
}

/** A project page: the active tab (a case tab names its item), then the project */
export function ProjectTitle({ pid, name }: { pid: string; name: string | undefined }) {
  const { t } = useTranslation()
  const active = useWorkbench((s) => s.active)
  const caseId = active?.type === 'case' && typeof active.caseId === 'string' ? active.caseId : null
  const itemId = caseId && typeof active?.itemId === 'string' ? active.itemId : null
  // the case tab's own query: no extra request
  const phase = useCase(pid, caseId).data?.items.find((i) => i.item_id === itemId)?.phase.canonical
  const tab = itemId ? itemName(itemId, t, phase) : active ? registry.getEditor<EditorParams>(active.type)?.title(active) : null
  useDocumentTitle(tab, name)
  return null
}
