// The dialogs and their strings load on first open, outside the initial bundle.
import { lazy, Suspense } from 'react'

import { useSetup } from './store'

const Storage = lazy(() => Promise.all([import('./StorageDialog'), import('../../i18n/lazy')]).then(([m]) => ({ default: m.StorageDialog })))
const Compute = lazy(() => Promise.all([import('./ComputeDialog'), import('../../i18n/lazy')]).then(([m]) => ({ default: m.ComputeDialog })))

export function SetupDialogs() {
  const shown = useSetup((s) => s.shown)
  const close = () => useSetup.getState().show(null)
  if (!shown) return null
  return <Suspense fallback={null}>{shown === 'storage' ? <Storage onClose={close} /> : <Compute onClose={close} />}</Suspense>
}
