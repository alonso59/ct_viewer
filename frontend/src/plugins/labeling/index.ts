import { createElement, lazy, Suspense } from 'react'

import i18n from '../../i18n'
import { keys, queryClient, type LabelTableInfo } from '../../api'
import { useWorkbench } from '../../shell'
import { codicon } from '../../theme'
import { revealView, type FrontendPlugin } from '../host'
import { useNewTable } from './store'
import type { TableParams } from './TableEditor'

const View = lazy(() => Promise.all([import('./LabelingView'), import('../../i18n/lazy')]).then(([m]) => m))
const Editor = lazy(() => Promise.all([import('./TableEditor'), import('../../i18n/lazy')]).then(([m]) => m))

const Section = lazy(() => Promise.all([import('./InspectorLabels'), import('../../i18n/lazy')]).then(([m]) => m))

const LazyView = () => createElement(Suspense, { fallback: null }, createElement(View))
const LazySection = () => createElement(Suspense, { fallback: null }, createElement(Section))
const LazyEditor = (props: { params: TableParams; panelId: string; active: boolean }) => createElement(Suspense, { fallback: null }, createElement(Editor, props))

const tableName = (tid: string) => {
  const pid = useWorkbench.getState().pid ?? ''
  return queryClient.getQueryData<LabelTableInfo[]>(keys.labelTables(pid))?.find((t) => t.table_id === tid)?.name ?? i18n.t('view.labeling')
}

export const plugin: FrontendPlugin = {
  id: 'labeling',
  activate: ({ registry }) => {
    registry.view({ id: 'labeling', title: 'view.labeling', icon: codicon('table'), order: 35, component: LazyView, hideImageSection: true })
    // fill the case's / scan's cells next to the images
    registry.inspector({ id: 'labeling.cells', title: 'inspector.labels', order: 15, component: LazySection })
    registry.editor<TableParams>({
      type: 'labeling',
      component: LazyEditor,
      id: (p) => `labeling:${p.tableId}`,
      title: (p) => tableName(p.tableId),
      icon: () => codicon('table'),
      path: (pid, p) => `/p/${pid}/labeling/${p.tableId}`,
      match: (path) => {
        const m = /^\/labeling\/([^/]+)$/.exec(path)
        return m?.[1] ? { tableId: m[1] } : null
      },
    })
    registry.command({
      id: 'labeling.newTable',
      writes: true,
      title: 'cmd.newLabelTable',
      category: 'cat.edit',
      keywords: ['kw.labeling'],
      menuGroup: 4,
      run: () => {
        revealView('labeling')
        useNewTable.getState().set(true)
      },
    })
  },
  open: () => revealView('labeling'),
}
