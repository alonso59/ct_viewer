// Viewer-only UI state that no other feature reads (the shared part is state/viewerSync).
import { create } from 'zustand'

import type { ViewerHandle } from './model/types'

interface LocalState {
  /** VW-06: zoom/pan linked across the 2D views */
  linkZoom: boolean
  /** VW-09 3D viewport */
  volume3d: boolean
  surfaces: boolean
  blend: number
  /** Handle of the visible case tab (screenshot, VW-16 context) */
  active: ViewerHandle | null
}

export const useViewerLocal = create<LocalState>()(() => ({
  linkZoom: true,
  volume3d: true,
  surfaces: false,
  blend: 1,
  active: null,
}))
