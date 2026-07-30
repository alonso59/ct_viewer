export type MprRendererMode = 'png'

export const DEFAULT_MPR_RENDERER_MODE: MprRendererMode = 'png'
export const MPR_RENDERER_STORAGE_KEY = 'radiology-ui-mpr-renderer'

export function normalizeMprRendererMode(value: unknown): MprRendererMode | null {
  if (typeof value !== 'string') {
    return null
  }

  const normalized = value.trim().toLowerCase()
  return normalized === 'png' ? 'png' : null
}

export function getBrowserMprRendererOverride(): MprRendererMode | null {
  if (typeof window === 'undefined') {
    return null
  }

  const params = new URLSearchParams(window.location.search)
  const queryMode =
    normalizeMprRendererMode(params.get('mpr_renderer')) ??
    normalizeMprRendererMode(params.get('mprRenderer'))
  if (queryMode) {
    return queryMode
  }

  try {
    return normalizeMprRendererMode(window.localStorage.getItem(MPR_RENDERER_STORAGE_KEY))
  } catch {
    return null
  }
}

export function resolveMprRendererMode(runtimeMode?: unknown): MprRendererMode {
  return (
    getBrowserMprRendererOverride() ??
    normalizeMprRendererMode(runtimeMode) ??
    DEFAULT_MPR_RENDERER_MODE
  )
}
