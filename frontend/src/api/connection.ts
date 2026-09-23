// Client-side API state that is not server data: live/offline state of the API-40 stream (UI-07)
// and a thumbnail epoch bumped when a thumbnail job finishes, so images that 404'd retry (IMP-12).
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
