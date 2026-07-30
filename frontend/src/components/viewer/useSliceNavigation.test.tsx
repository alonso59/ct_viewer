import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useSliceNavigation } from './useSliceNavigation'

describe('useSliceNavigation', () => {
  it('maps voxel indices to axis slices and normalized crosshair positions', () => {
    const { result } = renderHook(() => useSliceNavigation([4, 5, 6], 'series-a'))

    expect(result.current.sliceIndices).toEqual({
      axial: 3,
      coronal: 2,
      sagittal: 2,
    })
    expect(result.current.getMaxIndex('axial')).toBe(5)
    expect(result.current.getMaxIndex('coronal')).toBe(4)
    expect(result.current.getMaxIndex('sagittal')).toBe(3)
    expect(result.current.getCrosshair('axial')).toEqual({
      x: 2 / 3,
      y: 0.5,
    })
    expect(result.current.getCrosshair('coronal')).toEqual({
      x: 2 / 3,
      y: 0.4,
    })
    expect(result.current.getCrosshair('sagittal')).toEqual({
      x: 0.5,
      y: 0.4,
    })
  })

  it('updates the coordinated voxel point from panel clicks and slice changes', () => {
    const { result } = renderHook(() => useSliceNavigation([4, 5, 6], 'series-a'))

    act(() => result.current.setFromPanelPosition('axial', { x: 0, y: 1 }))
    expect(result.current.crosshairPoint).toEqual({ x: 0, y: 0, z: 3 })

    act(() => result.current.setFromPanelPosition('coronal', { x: 1, y: 0 }))
    expect(result.current.crosshairPoint).toEqual({ x: 3, y: 0, z: 5 })

    act(() => result.current.setFromPanelPosition('sagittal', { x: 0.25, y: 0.75 }))
    expect(result.current.crosshairPoint).toEqual({ x: 3, y: 1, z: 1 })

    act(() => result.current.setSlice('axial', 4))
    act(() => result.current.setSlice('coronal', 3))
    act(() => result.current.setSlice('sagittal', 2))
    expect(result.current.crosshairPoint).toEqual({ x: 2, y: 3, z: 4 })
  })
})
