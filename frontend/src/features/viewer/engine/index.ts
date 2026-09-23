// Engine factory. Callers get a ViewerHandle and never see NiiVue (VIEWER.md wrapper contract).
import type { ViewerHandle } from '../model/types'

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

/**
 * Creates the engine canvas inside `host` (first child, under the viewport frames).
 * NiiVue is loaded on first use so it stays out of the initial bundle (FE-05, NFR-07).
 */
export async function createViewer(host: HTMLElement): Promise<ViewerHandle> {
  const { NiivueViewer } = await import('./NiivueViewer')
  return new NiivueViewer(host)
}

export { VolumeFetchError } from './fetchVolume'
