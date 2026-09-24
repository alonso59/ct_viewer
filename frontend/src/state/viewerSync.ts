// Viewer state shared by the tool bar, status bar, inspector and the case editor (VW-*).
import { create } from 'zustand'

export type LayoutId =
  | 'four-up'
  | 'conventional'
  | 'three-mpr'
  | 'one-up-axial'
  | 'one-up-sagittal'
  | 'one-up-coronal'
  | 'one-up-3d'
export const LAYOUT_CYCLE: LayoutId[] = ['four-up', 'conventional', 'three-mpr', 'one-up-axial']
/** VW-06 tools + VW-17 measurements */
export type ViewerTool = 'pan' | 'window' | 'crosshair' | 'zoom' | 'distance' | 'angle' | 'roi'
export type ViewportId = 'axial' | 'sagittal' | 'coronal' | '3d'

// VW-05 presets (ww / wl)
export const WL_PRESETS = {
  soft_tissue: [400, 50],
  bone: [1800, 400],
  lung: [1500, -600],
  brain: [80, 40],
  kidney: [500, 100],
} as const
export type WlPreset = keyof typeof WL_PRESETS | 'custom'

/** VW-22/23/25 display options of the 2D tiles (project `display` or Open-mode defaults) */
export interface ViewerDisplay {
  invert: boolean
  slab: { mode: 'none' | 'mip' | 'minip' | 'avg'; mm: number }
  interpolation: 'linear' | 'nearest'
  convention: 'radiological' | 'neurological'
}

export interface WindowPreset {
  name: string
  ww: number
  wl: number
}

export interface CursorReadout {
  ijk: [number, number, number]
  ras: [number, number, number]
  value: number
  label: number
}

interface ViewerSyncState {
  activeCaseId: string | null
  activeItemId: string | null
  /** VW-19: the segmentation set shown and curated; null = the project's `default_seg` */
  activeSeg: string | null
  viewerFocused: boolean
  tool: ViewerTool
  layout: LayoutId
  maximized: ViewportId | null
  ww: number
  wl: number
  preset: WlPreset
  overlay: boolean
  outline: boolean
  crosshair: boolean
  overlayOpacity: number
  labelVisibility: Record<number, boolean>
  labelOpacity: Record<number, number>
  cursor: CursorReadout | null
  resetToken: number
  /** VW-05: display-only modality chosen for items without one, keyed by `modalityKey(item)` */
  modalityOverride: Record<string, string>
  /** VW-05: modality of the visible viewer's item; `assumed` = the item has none (selector shown) */
  activeModality: { key: string; value: string; assumed: boolean } | null
  display: ViewerDisplay
  /** VW-25: initial CT window (project `display.wl.CT`, else soft tissue) */
  ctWindow: [number, number]
  /** VW-25: project W/L presets (`display.wl_presets`); empty = the built-in presets */
  customPresets: WindowPreset[]
  /** VW-22: open on the DICOM header window when the item has one */
  useDicomWindow: boolean
  /** PRJ-14: the modality assumed for items without one */
  defaultModality: string
  /** VW-17: bumping it clears the measurements of the visible viewer */
  measureClear: number
  set: (patch: Partial<ViewerSyncState>) => void
  setModality: (key: string, modality: string) => void
  setPreset: (p: keyof typeof WL_PRESETS) => void
  setWindow: (ww: number, wl: number) => void
  cycleLayout: () => void
  toggleLabel: (value: number, fallback: boolean) => void
  reset: () => void
}

export const useViewerSync = create<ViewerSyncState>()((set, get) => ({
  activeCaseId: null,
  activeItemId: null,
  activeSeg: null,
  viewerFocused: false,
  tool: 'crosshair',
  layout: 'four-up',
  maximized: null,
  ww: 400,
  wl: 50,
  preset: 'soft_tissue',
  overlay: true,
  outline: false,
  crosshair: true,
  overlayOpacity: 1,
  labelVisibility: {},
  labelOpacity: {},
  cursor: null,
  resetToken: 0,
  modalityOverride: {},
  activeModality: null,
  display: { invert: false, slab: { mode: 'none', mm: 10 }, interpolation: 'linear', convention: 'radiological' },
  ctWindow: [400, 50],
  customPresets: [],
  useDicomWindow: true,
  defaultModality: 'CT',
  measureClear: 0,
  set: (patch) => set(patch),
  setModality: (key, modality) =>
    set((s) => ({
      modalityOverride: { ...s.modalityOverride, [key]: modality },
      activeModality: s.activeModality?.key === key ? { ...s.activeModality, value: modality } : s.activeModality,
    })),
  setPreset: (p) => set({ preset: p, ww: WL_PRESETS[p][0], wl: WL_PRESETS[p][1] }),
  setWindow: (ww, wl) => set({ ww: Math.max(1, Math.round(ww)), wl: Math.round(wl), preset: 'custom' }),
  cycleLayout: () => {
    const i = LAYOUT_CYCLE.indexOf(get().layout)
    set({ layout: LAYOUT_CYCLE[(i + 1) % LAYOUT_CYCLE.length] ?? 'four-up', maximized: null })
  },
  toggleLabel: (value, fallback) =>
    set((s) => ({ labelVisibility: { ...s.labelVisibility, [value]: !(s.labelVisibility[value] ?? fallback) } })),
  reset: () =>
    set((s) => {
      const soft = s.ctWindow[0] === WL_PRESETS.soft_tissue[0] && s.ctWindow[1] === WL_PRESETS.soft_tissue[1]
      return { resetToken: s.resetToken + 1, maximized: null, ww: s.ctWindow[0], wl: s.ctWindow[1], preset: soft ? 'soft_tissue' : 'custom' }
    }),
}))
