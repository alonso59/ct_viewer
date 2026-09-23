import { rollup } from './server'
import { defaultSettings, validateSettings } from './schema'

const sel = { labels: [2], items: 10 }
const msgs = (s: Record<string, unknown>, selection = sel) => validateSettings({ ...defaultSettings(), ...s }, selection).map((i) => i.message)

describe('curation rollup (CUR-08)', () => {
  test('worst status wins by severity', () => {
    expect(rollup([])).toBe('not_reviewed')
    expect(rollup(['accepted', 'needs_minor_correction'])).toBe('needs_minor_correction')
    expect(rollup(['needs_minor_correction', 'rejected', 'accepted'])).toBe('rejected')
    expect(rollup(['cannot_assess', 'accepted'])).toBe('cannot_assess')
  })
})

describe('radiomics validation (RAD-04)', () => {
  test('engine defaults are valid', () => {
    expect(validateSettings(defaultSettings(), sel)).toEqual([])
  })
  test('bin width xor bin count', () => {
    expect(msgs({ binWidth: 25, binCount: 32 })).toContain('Choose bin width or bin count')
    expect(msgs({ binWidth: null, binCount: null })).toContain('Choose bin width or bin count')
    expect(msgs({ binWidth: null, binCount: 32 })).toEqual([])
  })
  test('LoG needs a positive sigma', () => {
    expect(msgs({ 'imageType.LoG': true, sigma: [] })).toContain('LoG needs at least one sigma')
    expect(msgs({ 'imageType.LoG': true, sigma: [1, 2] })).toEqual([])
  })
  test('2D options need force2D', () => {
    expect(msgs({ 'featureClass.shape2D': true })).toContain('Enable 2D mode for this option')
    expect(msgs({ 'featureClass.shape2D': true, force2D: true })).toEqual([])
  })
  test('spacing and resegmentation ranges', () => {
    expect(msgs({ resampledPixelSpacing: [1, -1, 1] })).toContain('Spacing must be positive')
    expect(msgs({ resegmentRange: [100, -100] })).toContain('Minimum must be below maximum')
    expect(msgs({ resegmentMode: 'sigma', resegmentRange: [3] })).toEqual([])
  })
  test('nothing to extract', () => {
    expect(msgs({}, { labels: [], items: 10 })).toContain('Nothing to extract')
    expect(msgs({ 'imageType.Original': false })).toContain('Nothing to extract')
  })
})
