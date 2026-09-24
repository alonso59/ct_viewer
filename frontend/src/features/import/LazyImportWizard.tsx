// The wizard's code loads on first open (NFR-07); the store stays eager for commands and buttons
import { Suspense, lazy } from 'react'

import { useImportWizard } from './store'

const Wizard = lazy(() => import('./ImportWizard'))

export function ImportWizard() {
  const pid = useImportWizard((s) => s.pid)
  const prefill = useImportWizard((s) => s.prefill)
  return pid ? (
    <Suspense fallback={null}>
      <Wizard key={pid} pid={pid} prefill={prefill} />
    </Suspense>
  ) : null
}
