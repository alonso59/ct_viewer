// Feature-only radiomics hooks; the server state itself goes through `api/` (FE-02).
import { useEffect, useState } from 'react'

import { useRadiomicsValidation } from '../../api'
import type { WireSettings } from './model/types'

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

type Body = { settings: WireSettings; labels: number[]; nItems: number | null }

/** Authoritative validation (API-31), debounced; `isCurrent` is false while the form is ahead of the answer */
export function useServerValidation(settings: WireSettings | null, labels: number[], nItems: number | null) {
  const body = settings ? JSON.stringify({ settings, labels, nItems }) : null
  const debounced = useDebounced(body, 300)
  const q = useRadiomicsValidation(debounced === null ? null : (JSON.parse(debounced) as Body))
  return { ...q, isCurrent: debounced === body && !q.isPlaceholderData && q.isSuccess }
}
