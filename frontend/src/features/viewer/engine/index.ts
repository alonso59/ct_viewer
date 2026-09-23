// Engine factory. Callers get a ViewerHandle and never see NiiVue (VIEWER.md wrapper contract).
import type { ViewerHandle } from '../model/types'
import { NiivueViewer } from './NiivueViewer'

export function hasWebgl2(): boolean {
  try {
    const gl = document.createElement('canvas').getContext('webgl2')
    // Browsers cap live contexts; do not keep the probe alive
    gl?.getExtension('WEBGL_lose_context')?.loseContext()
    return !!gl
  } catch {
    return false
  }
}

/** Creates the engine canvas inside `host` (first child, under the viewport frames) */
export function createViewer(host: HTMLElement): ViewerHandle {
  return new NiivueViewer(host)
}

export { VolumeFetchError } from './fetchVolume'
