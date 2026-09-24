// VW-25 / PRJ-14: project display settings → the viewer store; Open mode uses the defaults.
import type { Project } from '../../api'
import { useViewerSync, type ViewerDisplay } from '../../state'

const DEFAULT: ViewerDisplay = { invert: false, slab: { mode: 'none', mm: 10 }, interpolation: 'linear', convention: 'radiological' }

/** `withLayout`: also apply the initial layout (not when the URL names one, FE-04) */
export function applyProjectDisplay(p: Project, withLayout: boolean) {
  const d = p.display
  const ct = d.wl?.CT
  const ctWindow: [number, number] = ct && typeof ct === 'object' ? [ct.ww, ct.wl] : [400, 50]
  useViewerSync.setState((s) => ({
    display: { ...s.display, interpolation: d.interpolation ?? 'linear', convention: d.convention ?? 'radiological' },
    ctWindow,
    customPresets: (d.wl_presets ?? []).map((x) => ({ name: x.name, ww: x.ww, wl: x.wl })),
    useDicomWindow: d.use_dicom_window ?? true,
    defaultModality: p.default_modality,
    ...(withLayout && d.layout ? { layout: d.layout, maximized: null } : {}),
  }))
}

/** Open mode (no project): the built-in display defaults */
export function resetDisplay() {
  useViewerSync.setState({ display: DEFAULT, ctWindow: [400, 50], customPresets: [], useDicomWindow: true, defaultModality: 'CT' })
}
