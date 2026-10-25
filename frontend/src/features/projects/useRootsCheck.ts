// On opening a project, offer Relink when a path alias does not resolve
import { useState } from 'react'

import { useRoots } from '../../api'

export function useRootsCheck(pid: string) {
  const roots = useRoots(pid)
  const [dismissed, setDismissed] = useState<string | null>(null)
  const missing = (roots.data ?? []).some((r) => !r.exists)
  return { open: missing && dismissed !== pid, dismiss: () => setDismissed(pid) }
}
