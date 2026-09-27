// DICOM converter plugin (plugins/dicom, DCM-*): the `dicom.convert` task, its command and the
// converter overlay window (UI-25), which loads with its strings on first open (NFR-07).
import { createElement, lazy, Suspense } from 'react'

import { useWorkbench } from '../../shell'
import type { FrontendPlugin } from '../host'
import { useConverter } from './store'

export { useConverter } from './store'

const Overlay = lazy(() => Promise.all([import('./ConverterOverlay'), import('../../i18n/lazy')]).then(([m]) => m))

function ConverterHost() {
  const open = useConverter((s) => s.open)
  return open ? createElement(Suspense, { fallback: null }, createElement(Overlay)) : null
}

/** Opens the converter; inside a project it can convert into that project (DCM-14). */
export const openConverter = (source?: string | null) => useConverter.getState().show({ source, pid: useWorkbench.getState().pid })

export const plugin: FrontendPlugin = {
  id: 'dicom',
  activate: ({ registry }) => {
    registry.overlay({ id: 'dicom.converter', component: ConverterHost })
    registry.command({ id: 'tasks.convertDicom', writes: true, title: 'cmd.convertDicom', category: 'cat.tasks', scope: ['home', 'open', 'project'], menuGroup: 1, run: (source) => openConverter(source) })
  },
  open: () => openConverter(),
}
