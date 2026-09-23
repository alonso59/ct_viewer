// Reviewer identity (CUR-01, FE-10): a free-text stamp kept in localStorage. No accounts (ADR-0004).
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface ReviewerState {
  name: string
  /** Set while a write is waiting for the reviewer prompt */
  prompting: boolean
  setName: (name: string) => void
  setPrompting: (v: boolean) => void
}

export const useReviewer = create<ReviewerState>()(
  persist(
    (set) => ({
      name: '',
      prompting: false,
      setName: (name) => set({ name: name.trim(), prompting: false }),
      setPrompting: (prompting) => set({ prompting }),
    }),
    { name: 'rw.reviewer', partialize: (s) => ({ name: s.name }) },
  ),
)

let pending: ((name: string | null) => void) | null = null

/** Resolve the reviewer name, prompting once if it is not set yet (CUR-01). */
export function requireReviewer(): Promise<string | null> {
  const { name, setPrompting } = useReviewer.getState()
  if (name) return Promise.resolve(name)
  setPrompting(true)
  return new Promise((resolve) => {
    pending = resolve
  })
}

/** Open the prompt to change the current name (status bar click) */
export function changeReviewer(): Promise<string | null> {
  useReviewer.getState().setPrompting(true)
  return new Promise((resolve) => {
    pending = resolve
  })
}

export function resolveReviewerPrompt(name: string | null) {
  if (name) useReviewer.getState().setName(name)
  else useReviewer.getState().setPrompting(false)
  pending?.(name)
  pending = null
}
