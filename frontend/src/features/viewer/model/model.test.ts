// VW-01/04/05/07 pure viewer logic
import { lutRows, lutWidth, niivueLut, hexToRgb } from './labels'
import { CROSS, LAYOUT_IDS, isLayoutId, visibleViewports } from './layouts'
import type { LabelStyle } from './types'
import { dragWindow, isCt, percentileWindow, windowToRange } from './wl'

const L = (value: number, p: Partial<LabelStyle> = {}): LabelStyle => ({ value, color: '#ff8000', visible: true, opacity: 0.5, outline: false, ...p })

describe('labels (VW-07)', () => {
  test('hexToRgb handles short and long forms', () => {
    expect(hexToRgb('#ff8000')).toEqual([255, 128, 0])
    expect(hexToRgb('#0f0')).toEqual([0, 255, 0])
    expect(hexToRgb('nope')).toEqual([255, 255, 255])
  })

  test('lutRows: colour + per-label opacity in row 0, outline flag in row 1, hidden = transparent', () => {
    const w = 4
    const rows = lutRows([L(1), L(2, { visible: false }), L(3, { outline: true, opacity: 0.2 })], w)
    expect(rows.length).toBe(w * 2 * 4)
    expect([...rows.slice(4, 8)]).toEqual([255, 128, 0, 128])
    expect(rows[2 * 4 + 3]).toBe(0) // hidden
    expect(rows[3 * 4 + 3]).toBe(51)
    expect(rows[(w + 3) * 4]).toBe(255) // outline flag
    expect(rows[(w + 1) * 4]).toBe(0)
    expect(rows[3]).toBe(0) // background never drawn
  })

  test('lutWidth covers the mask maximum and every label value', () => {
    expect(lutWidth([L(1), L(7)], 3)).toBe(8)
    expect(lutWidth([L(1)], 40)).toBe(41)
  })

  test('niivueLut is binary visibility for the 3D tile', () => {
    const lut = niivueLut([L(1), L(2, { visible: false })], 3)
    expect(lut.A).toEqual([0, 255, 0])
    expect(lut.I).toEqual([0, 1, 2])
  })
})

describe('layouts (VW-01/02/04)', () => {
  test('all layouts known; URL values validated', () => {
    expect(LAYOUT_IDS).toContain('four-up')
    expect(isLayoutId('conventional')).toBe(true)
    expect(isLayoutId('bogus')).toBe(false)
    expect(isLayoutId(null)).toBe(false)
  })

  test('maximize shows one viewport', () => {
    expect(visibleViewports('four-up', null)).toEqual(['axial', 'sagittal', 'coronal', '3d'])
    expect(visibleViewports('four-up', 'coronal')).toEqual(['coronal'])
    expect(visibleViewports('three-mpr', null)).toHaveLength(3)
  })

  test('crosshair lines follow 3D Slicer: each view shows the other two planes', () => {
    for (const [plane, lines] of Object.entries(CROSS)) {
      expect(lines).not.toContain(plane)
      expect(new Set(lines).size).toBe(2)
    }
  })
})

describe('window / level (VW-05)', () => {
  test('HU presets only for CT; missing modality counts as CT', () => {
    expect(isCt({ extra: {} })).toBe(true)
    expect(isCt({ extra: { modality: 'ct' } })).toBe(true)
    expect(isCt({ extra: { modality: 'MR' } })).toBe(false)
  })

  test('drag: right = wider, up = higher level; width never below 1', () => {
    expect(dragWindow([400, 50], 10, 0, 1000)).toEqual([420, 50])
    expect(dragWindow([400, 50], 0, -10, 1000)).toEqual([400, 60])
    expect(dragWindow([10, 0], -1000, 0, 1000)[0]).toBe(1)
  })

  test('percentile window spans the 1st–99th percentile', () => {
    const data = Float32Array.from({ length: 10000 }, (_, i) => i)
    const [ww, wl] = percentileWindow(data)
    const [lo, hi] = windowToRange(ww, wl)
    expect(lo).toBeGreaterThan(90)
    expect(lo).toBeLessThan(110)
    expect(hi).toBeGreaterThan(9890)
    expect(hi).toBeLessThan(9910)
  })

  test('percentile window applies slope/intercept', () => {
    const [, wl] = percentileWindow(Int16Array.from([0, 0, 100, 100]), 2, -1000)
    expect(wl).toBe(-900)
  })
})
