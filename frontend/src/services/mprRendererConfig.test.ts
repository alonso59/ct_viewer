import { afterEach, describe, expect, it } from 'vitest'

import {
  MPR_RENDERER_STORAGE_KEY,
  normalizeMprRendererMode,
  resolveMprRendererMode,
} from './mprRendererConfig'

describe('mpr renderer runtime config', () => {
  afterEach(() => {
    window.history.replaceState(null, '', '/')
    window.localStorage.removeItem(MPR_RENDERER_STORAGE_KEY)
  })

  it('normalizes supported renderer modes only', () => {
    expect(normalizeMprRendererMode('png')).toBe('png')
    expect(normalizeMprRendererMode('Cornerstone')).toBeNull()
    expect(normalizeMprRendererMode('auto')).toBeNull()
    expect(normalizeMprRendererMode('dicom')).toBeNull()
    expect(normalizeMprRendererMode(null)).toBeNull()
  })

  it('defaults to png without runtime configuration', () => {
    expect(resolveMprRendererMode()).toBe('png')
    expect(resolveMprRendererMode('invalid')).toBe('png')
  })

  it('uses backend runtime configuration when present', () => {
    expect(resolveMprRendererMode('png')).toBe('png')
    expect(resolveMprRendererMode('auto')).toBe('png')
    expect(resolveMprRendererMode('cornerstone')).toBe('png')
  })

  it('lets browser runtime overrides win over backend configuration', () => {
    window.localStorage.setItem(MPR_RENDERER_STORAGE_KEY, 'png')
    expect(resolveMprRendererMode('cornerstone')).toBe('png')

    window.history.replaceState(null, '', '/viewer?mpr_renderer=auto')
    expect(resolveMprRendererMode('png')).toBe('png')
  })
})
