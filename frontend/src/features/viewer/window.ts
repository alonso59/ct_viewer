// Applying a modality's window to the shared W/L store.
import { useViewerSync } from '../../state'
import type { ViewerHandle } from './model/types'

/** The project's CT window (a preset name when it is soft tissue) */
export function applyCtWindow() {
  const s = useViewerSync.getState()
  const [ww, wl] = s.ctWindow
  if (ww === 400 && wl === 50) s.setPreset('soft_tissue')
  else s.setWindow(ww, wl)
}

/** The 1st–99th percentile window of the loaded image: the default for anything but CT */
export function applyAutoWindow(handle: Pick<ViewerHandle, 'defaultWindow'>) {
  const [ww, wl] = handle.defaultWindow()
  useViewerSync.getState().setWindow(ww, wl)
}
