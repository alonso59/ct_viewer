// Viewer-only UI state that no other feature reads (the shared part is state/viewerSync).
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { ItemRecord } from '../../api'
import type { Scene3DOptions, ViewerHandle, ViewportId } from './model/types'
import { DEFAULT_SCENE_3D } from './model/scene3d'

interface LocalState {
  /** Zoom/pan linked across the 2D views (opt-in, not persisted) */
  linkZoom: boolean
  /** Viewport under the pointer (target of `F`) */
  hovered: ViewportId | null
  volume3d: boolean
  mask3d: boolean
  ctOpacity: number
  surfaces: boolean
  blend: number
  scene3d: Scene3DOptions
  /** Handle of the visible case tab (screenshot, curation context) */
  active: ViewerHandle | null
  /** Header info of the visible viewer's item */
  info: { item: ItemRecord; tags?: () => Promise<Record<string, unknown>> } | null
}

export const useViewerLocal = create<LocalState>()(persist((): LocalState => ({
  linkZoom: false,
  hovered: null,
  volume3d: true,
  mask3d: true,
  ctOpacity: 1,
  surfaces: true,
  blend: 1,
  scene3d: DEFAULT_SCENE_3D,
  active: null,
  info: null,
}), {
  name: 'rw.viewer3d',
  version: 1,
  // Enable smooth mask surfaces once for existing viewers; retain their other display choices.
  migrate: (saved) => ({ ...(saved as Partial<LocalState>), surfaces: true }),
  partialize: ({ volume3d, mask3d, ctOpacity, surfaces, blend, scene3d }) => ({ volume3d, mask3d, ctOpacity, surfaces, blend, scene3d }),
}))
