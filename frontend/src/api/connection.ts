// Live/offline state of the event stream, and a thumbnail epoch bumped when a thumbnail job
// finishes so images that 404'd retry.
import { useEffect, useState } from 'react'
import { create } from 'zustand'

import type { ConnectionState } from './surface'

interface ConnectionStore {
  state: ConnectionState
  /** When `state` last changed (ms since epoch) */
  since: number
  thumbEpoch: number
  set: (s: ConnectionState) => void
  bumpThumbs: () => void
}

export const useConnection = create<ConnectionStore>()((set) => ({
  state: 'connecting',
  since: Date.now(),
  thumbEpoch: 0,
  set: (state) => set((s) => (s.state === state ? s : { state, since: Date.now() })),
  bumpThumbs: () => set((s) => ({ thumbEpoch: s.thumbEpoch + 1 })),
}))

/** After this long without the stream, live views say their updates are paused and poll instead */
export const STALE_MS = 10_000
/** Live views poll this often while the stream is down */
export const POLL_MS = 3_000

/** True once the event stream has been down for STALE_MS */
export function useStaleLive(): boolean {
  const down = useConnection((s) => s.state !== 'live')
  const since = useConnection((s) => s.since)
  // the outage (by its start) that has lasted STALE_MS
  const [staleSince, setStaleSince] = useState<number | null>(null)
  useEffect(() => {
    if (!down) return
    const timer = setTimeout(() => setStaleSince(since), Math.max(0, since + STALE_MS - Date.now()))
    return () => clearTimeout(timer)
  }, [down, since])
  return down && staleSince === since
}
