// DICOM converter plugin (plugins/dicom, DCM-*): the `dicom.convert` task, its command and the
// converter overlay window (UI-25), which loads with its strings on first open (NFR-07).
import { createElement, lazy, Suspense, useEffect } from 'react'

import { isTaskRunPending, isViewPid, useSourceOperations } from '../../api'
import { useWorkbench } from '../../shell'
import type { FrontendPlugin } from '../host'
import { useConverter } from './store'

const Overlay = lazy(() => Promise.all([import('./ConverterOverlay'), import('../../i18n/lazy')]).then(([m]) => m))

function ConverterHost() {
  const viewOnly = isViewPid(useWorkbench((s) => s.pid))
  const open = useConverter((s) => s.open)
  const session = useConverter((s) => s.session)
  const selected = useConverter((s) => s.operationId)
  const minimized = useConverter((s) => s.minimized)
  const operations = useSourceOperations(!viewOnly).data
  useEffect(() => {
    if (viewOnly || open || !operations) return
    const restored = operations.find((operation) => operation.operation_id === selected)
      ?? operations.find((operation) => isTaskRunPending(operation.status))
    if (restored) useConverter.getState().attach(restored.operation_id, selected ? minimized : true)
  }, [viewOnly, open, operations, selected, minimized])
  return open && !viewOnly ? createElement(Suspense, { fallback: null }, createElement(Overlay, { key: session })) : null
}

/** Opens the converter; inside a project it can convert into that project (DCM-14). */
export const openConverter = (source?: string | null) => useConverter.getState().show({ source, pid: useWorkbench.getState().pid })

export const plugin: FrontendPlugin = {
  id: 'dicom',
  activate: ({ registry }) => {
    registry.overlay({ id: 'dicom.converter', component: ConverterHost })
    registry.command({ id: 'sources.openBackground', writes: true, title: 'home.sourceOperations', scope: ['home', 'open', 'project'], menu: false, run: (id) => { const state = useConverter.getState(); if (id) state.attach(id, false, true); else if (state.operationId) state.attach(state.operationId); else openConverter() } })
    registry.command({ id: 'tasks.convertDicom', writes: true, title: 'cmd.convertDicom', category: 'cat.tasks', scope: ['home', 'open', 'project'], menuGroup: 1, run: (source) => openConverter(source) })
  },
  open: () => openConverter(),
}
