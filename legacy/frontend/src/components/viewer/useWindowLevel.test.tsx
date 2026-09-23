import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useWindowLevel } from './useWindowLevel'

describe('useWindowLevel', () => {
  it('preserves preset, custom range, and drag window/level behavior', () => {
    const { result } = renderHook(() => useWindowLevel())

    expect(result.current.activePreset).toBe('softTissue')
    expect(result.current.ww).toBe(400)
    expect(result.current.wl).toBe(50)

    act(() => result.current.applyPreset('bone'))
    expect(result.current.ww).toBe(2000)
    expect(result.current.wl).toBe(400)

    act(() => result.current.setWindowRange(-100, 200))
    expect(result.current.activePreset).toBe('custom')
    expect(result.current.ww).toBe(300)
    expect(result.current.wl).toBe(50)

    act(() => result.current.applyDrag(300, 50, 10, -5))
    expect(result.current.activePreset).toBe('custom')
    expect(result.current.ww).toBe(360)
    expect(result.current.wl).toBe(65)
  })
})
