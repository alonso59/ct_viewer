import { createElement, lazy, Suspense, useEffect } from 'react'

import { isViewPid, useSourceOperations } from '../../api'
import { useWorkbench } from '../../shell'
import type { FrontendPlugin } from '../host'
import { useImportWizard } from '../../features/import'
import { useConverter } from './store'

const Overlay = lazy(() => Promise.all([import('./ConverterOverlay'), import('../../i18n/lazy')]).then(([m]) => m))

function ConverterHost() {
  const viewOnly = isViewPid(useWorkbench((s) => s.pid))
  const open = useConverter((s) => s.open)
  const session = useConverter((s) => s.session)
  const selected = useConverter((s) => s.operationId)
  const minimized = useConverter((s) => s.minimized)
  const importOpen = useImportWizard((s) => s.pid !== null)
  const operations = useSourceOperations(!viewOnly).data
  useEffect(() => {
    if (viewOnly || open || importOpen || !selected || !operations) return
    const restored = operations.find((operation) => operation.operation_id === selected)
    if (restored) useConverter.getState().attach(restored.operation_id, minimized)
  }, [viewOnly, open, importOpen, operations, selected, minimized])
  return open && !viewOnly ? createElement(Suspense, { fallback: null }, createElement(Overlay, { key: session })) : null
}

/** Opens the converter; inside a project it can convert into that project. */
export const openConverter = (source?: string | null) => useConverter.getState().show({ source, pid: useWorkbench.getState().pid })

export const plugin: FrontendPlugin = {
  id: 'dicom',
  activate: ({ registry }) => {
    registry.overlay({ id: 'dicom.converter', component: ConverterHost })
    registry.command({ id: 'sources.openBackground', writes: true, title: 'home.sourceOperations', scope: ['home', 'open', 'project'], menu: false, run: (id) => { const state = useConverter.getState(); if (id) state.attach(id, false, true); else if (state.operationId) state.attach(state.operationId); else openConverter() } })
    registry.command({ id: 'sources.minimizeBackground', writes: true, title: 'home.sourceOperations', scope: ['home', 'open', 'project'], menu: false, run: (id) => { if (id) useConverter.getState().attach(id, true) } })
    registry.command({ id: 'sources.dismissBackground', writes: true, title: 'home.sourceOperations', scope: ['home', 'open', 'project'], menu: false, run: () => useConverter.getState().close() })
    registry.command({ id: 'tasks.convertDicom', writes: true, title: 'cmd.convertDicom', category: 'cat.tasks', scope: ['home', 'open', 'project'], menuGroup: 1, run: (source) => openConverter(source) })
  },
  open: () => openConverter(),
}
