import { createElement, lazy, Suspense } from 'react'

import { registry } from '../../shell'
import { useOpenDialog } from './store'

export { useOpenDialog } from './store'
export { openPath } from '../../lib'

const Route = lazy(() => Promise.all([import('./OpenRoute'), import('../../i18n/lazy')]).then(([m]) => m))
const Dialog = lazy(() => Promise.all([import('./OpenDialog'), import('../../i18n/lazy')]).then(([m]) => m))

export function OpenRoute() {
  return createElement(Suspense, { fallback: null }, createElement(Route))
}

export function OpenDialogHost() {
  const open = useOpenDialog((s) => s.open)
  return open ? createElement(Suspense, { fallback: null }, createElement(Dialog)) : null
}

export function registerOpen() {
  registry.command({
    id: 'open.path',
    title: 'open.command',
    category: 'cat.file',
    scope: ['home', 'open', 'project'],
    menuGroup: 1,
    run: () => useOpenDialog.getState().show(),
  })
}
