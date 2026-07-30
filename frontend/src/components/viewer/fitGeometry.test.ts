import { describe, expect, it } from 'vitest'

import { computeContainRect, getPhysicalFitSize, normalizeVoxelSpacing } from './fitGeometry'

describe('viewer physical fit geometry', () => {
  it('uses X/Y spacing for axial slices', () => {
    expect(getPhysicalFitSize('axial', 200, 100, [0.7, 0.8, 5])).toEqual({
      width: 140,
      height: 80,
    })
  })

  it('uses X/Z spacing for coronal slices', () => {
    expect(getPhysicalFitSize('coronal', 200, 30, [0.7, 0.8, 5])).toEqual({
      width: 140,
      height: 150,
    })
  })

  it('uses Y/Z spacing for sagittal slices', () => {
    expect(getPhysicalFitSize('sagittal', 160, 30, [0.7, 0.8, 5])).toEqual({
      width: 128,
      height: 150,
    })
  })

  it('falls back to unit spacing for missing or invalid values', () => {
    expect(normalizeVoxelSpacing([0, Number.NaN, 2.5])).toEqual([1, 1, 2.5])
    expect(getPhysicalFitSize('coronal', 128, 64, undefined)).toEqual({
      width: 128,
      height: 64,
    })
  })

  it('contains the physical content rectangle inside a fixed pane', () => {
    const rect = computeContainRect(500, 300, 140, 150)

    expect(rect).not.toBeNull()
    expect(rect?.left).toBeCloseTo(0.22)
    expect(rect?.top).toBeCloseTo(0)
    expect(rect?.width).toBeCloseTo(0.56)
    expect(rect?.height).toBeCloseTo(1)
  })
})
