// Screen-reader announcements on a budget: one shared polite region hears milestones (started,
// stage changed, finished, failed, N results), at most one every few seconds; a newer message
// replaces one still waiting, so ticks and pointer moves never queue up.
import { useEffect } from 'react'
import { create } from 'zustand'

/** At least this long between two announcements */
export const ANNOUNCE_GAP_MS = 3000

interface AnnounceState {
  text: string
  pending: string | null
  last: number
  timer: ReturnType<typeof setTimeout> | null
}
export const useAnnouncer = create<AnnounceState>()(() => ({ text: '', pending: null, last: -Infinity, timer: null }))

export function announce(message: string) {
  const s = useAnnouncer.getState()
  useAnnouncer.setState({ pending: message })
  if (s.timer) return
  const timer = setTimeout(() => {
    const { pending, text } = useAnnouncer.getState()
    // the same words again still change the region, so they are read again
    useAnnouncer.setState({ text: pending === text ? `${pending}\u00a0` : pending ?? '', pending: null, last: Date.now(), timer: null })
  }, Math.max(0, s.last + ANNOUNCE_GAP_MS - Date.now()))
  useAnnouncer.setState({ timer })
}

/** Announce `message` each time it changes; pass a milestone (a stage, a result count), never a counter */
export function useAnnounce(message: string | null | undefined) {
  useEffect(() => {
    if (message) announce(message)
  }, [message])
}

/** The shared region, once per page */
export function Announcer() {
  const text = useAnnouncer((s) => s.text)
  return (
    <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true" data-testid="announcer">
      {text}
    </div>
  )
}
