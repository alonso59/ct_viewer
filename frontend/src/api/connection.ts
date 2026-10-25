// Live/offline state of the event stream, and a thumbnail epoch bumped when a thumbnail job
// finishes so images that 404'd retry.
import { create } from 'zustand'

import type { ConnectionState } from './surface'

interface ConnectionStore {
  state: ConnectionState
  thumbEpoch: number
  set: (s: ConnectionState) => void
  bumpThumbs: () => void
}

export const useConnection = create<ConnectionStore>()((set) => ({
  state: 'connecting',
  thumbEpoch: 0,
  set: (state) => set({ state }),
  bumpThumbs: () => set((s) => ({ thumbEpoch: s.thumbEpoch + 1 })),
}))
