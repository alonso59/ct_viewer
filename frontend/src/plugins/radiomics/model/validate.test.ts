// RAD-04 client validation mirrors API-43 (RADIOMICS.md §Validation rules)
import schemaJson from './fixtures/schema.json'
import { defaultForm, setFeatures, setFilter, setOption } from './settings'
import type { FormState, Issue, ServerIssue, SettingsSchema } from './types'
import { fieldOf, fromServer, hasErrors, validateForm, type ValidationContext } from './validate'

const schema = schemaJson as unknown as SettingsSchema
const ctx: ValidationContext = { labels: [2], nItems: null }
const base = () => defaultForm(schema)
const run = (form: FormState, c: Partial<ValidationContext> = {}) => validateForm(schema, form, { ...ctx, ...c })
const brief = (issues: Issue[]) => issues.map(({ rule, loc, severity, key }) => ({ rule, loc, severity, key }))
const err = (rule: string, loc: Issue['loc'], key: string) => ({ rule, loc, severity: 'error', key })

describe('validateForm (RAD-04)', () => {
  test('engine defaults are valid', () => {
    expect(run(base())).toEqual([])
  })

  describe('bin_xor', () => {
    test('binWidth and binCount both set', () => {
      expect(brief(run(setOption(base(), 'binCount', 10)))).toEqual([
        err('bin_xor', ['settings', 'binWidth'], 'binXor'),
        err('bin_xor', ['settings', 'binCount'], 'binXor'),
      ])
    })
    test('neither set', () => {
      expect(brief(run(setOption(base(), 'binWidth', null)))).toEqual([
        err('bin_xor', ['settings', 'binWidth'], 'binXor'),
        err('bin_xor', ['settings', 'binCount'], 'binXor'),
      ])
    })
    test('binCount alone is fine', () => {
      expect(run(setOption(setOption(base(), 'binWidth', null), 'binCount', 32))).toEqual([])
    })
  })

  describe('log_sigma', () => {
    const withLog = (sigma: number[] | null) => setFilter(base(), 'LoG', { enabled: true, params: { sigma } })
    test('empty sigma', () => {
      expect(brief(run(withLog([])))).toEqual([err('log_sigma', ['image_types', 'LoG', 'sigma'], 'logSigma')])
    })
    test.each([[[0]], [[-1]]])('sigma %j has no positive value', (sigma) => {
      expect(brief(run(withLog(sigma)))).toContainEqual(err('log_sigma', ['image_types', 'LoG', 'sigma'], 'logSigma'))
    })
    test('sigma [1, 2] is fine', () => {
      expect(run(withLog([1, 2]))).toEqual([])
    })
  })

  describe('force_2d', () => {
    const f = () => setFeatures(setFilter(base(), 'LBP2D', { enabled: true }), 'shape2D', ['Elongation'])
    test('shape2D and LBP2D without force2D', () => {
      expect(brief(run(f()))).toEqual([
        err('force_2d', ['features', 'shape2D'], 'force2d'),
        err('force_2d', ['image_types', 'LBP2D'], 'force2d'),
      ])
    })
    test('force2D=true clears both', () => {
      expect(run(setOption(f(), 'force2D', true))).toEqual([])
    })
  })

  describe('resampledPixelSpacing', () => {
    test('negative value flagged at its index; 0 keeps the axis', () => {
      expect(brief(run(setOption(base(), 'resampledPixelSpacing', [1, -1, 0])))).toEqual([
        err('constraint', ['settings', 'resampledPixelSpacing', 1], 'spacing'),
      ])
    })
    test('wrong length', () => {
      expect(brief(run(setOption(base(), 'resampledPixelSpacing', [1, 1])))).toEqual([
        err('constraint', ['settings', 'resampledPixelSpacing'], 'spacing'),
      ])
    })
    test('valid spacing', () => {
      expect(run(setOption(base(), 'resampledPixelSpacing', [1, 1, 0]))).toEqual([])
    })
  })

  describe('resegmentRange', () => {
    const reseg = (range: number[] | null, mode = 'absolute') => setOption(setOption(base(), 'resegmentMode', mode), 'resegmentRange', range)
    test('reseg_order: min >= max', () => {
      expect(brief(run(reseg([100, -100])))).toEqual([err('reseg_order', ['settings', 'resegmentRange'], 'resegOrder')])
    })
    test.each([[[1, 2]], [[-2]]])('reseg_sigma: %j in sigma mode', (range) => {
      expect(brief(run(reseg(range, 'sigma')))).toEqual([err('reseg_sigma', ['settings', 'resegmentRange'], 'resegSigma')])
    })
    test('sigma mode with one positive value', () => {
      expect(run(reseg([2], 'sigma'))).toEqual([])
    })
    test('sigma mode with no range', () => {
      expect(run(reseg(null, 'sigma'))).toEqual([])
    })
    test('too many values', () => {
      expect(brief(run(reseg([5, 6, 7])))).toEqual([err('constraint', ['settings', 'resegmentRange'], 'countRange')])
    })
    test('single value in absolute mode', () => {
      expect(run(reseg([5]))).toEqual([])
    })
    test('ordered pair', () => {
      expect(run(reseg([-100, 100]))).toEqual([])
    })
  })

  describe('nothing to extract', () => {
    test('no features', () => {
      let f = base()
      for (const c of schema.feature_classes) f = setFeatures(f, c.name, [])
      expect(brief(run(f))).toEqual([err('nothing', ['features'], 'nothing')])
    })
    test('no filter', () => {
      expect(brief(run(setFilter(base(), 'Original', { enabled: false })))).toEqual([err('nothing', ['image_types'], 'nothing')])
    })
    test('no labels', () => {
      expect(brief(run(base(), { labels: [] }))).toEqual([err('nothing', ['labels'], 'nothing')])
    })
    test('no items', () => {
      expect(brief(run(base(), { nItems: 0 }))).toEqual([err('nothing', ['n_items'], 'nothing')])
    })
    test('unknown item count is not checked', () => {
      expect(run(base(), { nItems: null })).toEqual([])
      expect(run(base(), { nItems: 3 })).toEqual([])
    })
  })

  describe('normalize_hu', () => {
    const f = (mode: string) => setOption(setOption(setOption(base(), 'normalize', true), 'resegmentRange', [-100, 100]), 'resegmentMode', mode)
    test('warning only, absolute mode', () => {
      const issues = run(f('absolute'))
      expect(brief(issues)).toEqual([{ rule: 'normalize_hu', loc: ['settings', 'normalize'], severity: 'warning', key: 'normalizeHu' }])
      expect(hasErrors(issues)).toBe(false)
    })
    test('relative mode: no warning', () => {
      expect(run(f('relative'))).toEqual([])
    })
    test('no range: no warning', () => {
      expect(run(setOption(base(), 'normalize', true))).toEqual([])
    })
  })

  test('unavailable filter (LBP3D)', () => {
    const issues = run(setFilter(base(), 'LBP3D', { enabled: true }))
    expect(brief(issues)).toEqual([err('unavailable', ['image_types', 'LBP3D'], 'unavailable')])
    expect(issues[0]?.params?.reason).toMatch(/trimesh/)
  })

  describe('type and constraint', () => {
    test('int out of range', () => {
      const issues = run(setOption(base(), 'minimumROIDimensions', 5))
      expect(brief(issues)).toEqual([err('constraint', ['settings', 'minimumROIDimensions'], 'range')])
      expect(issues[0]?.params).toEqual({ min: 1, max: 3 })
    })
    test('int given a float', () => {
      expect(brief(run(setOption(base(), 'minimumROIDimensions', 1.5)))).toEqual([err('type', ['settings', 'minimumROIDimensions'], 'integer')])
    })
    test('non-nullable null', () => {
      expect(brief(run(setOption(base(), 'normalize', null)))).toEqual([err('type', ['settings', 'normalize'], 'required')])
    })
    test('enum not in choices', () => {
      expect(brief(run(setOption(base(), 'interpolator', 'x')))).toEqual([err('constraint', ['settings', 'interpolator'], 'choice')])
    })
    test('list item at exclusive min', () => {
      expect(brief(run(setOption(base(), 'distances', [0])))).toEqual([err('constraint', ['settings', 'distances', 0], 'gt')])
    })
    test('binCount 0 (exclusive min)', () => {
      const f = setOption(setOption(base(), 'binWidth', null), 'binCount', 0)
      expect(brief(run(f))).toEqual([err('constraint', ['settings', 'binCount'], 'gt')])
    })
    test('non-finite number', () => {
      expect(brief(run(setOption(base(), 'normalizeScale', Number.NaN)))).toEqual([err('type', ['settings', 'normalizeScale'], 'number')])
    })
    test('filter param constraint (Wavelet level 0)', () => {
      const f = setFilter(base(), 'Wavelet', { enabled: true, params: { level: 0 } })
      expect(brief(run(f))).toEqual([err('constraint', ['image_types', 'Wavelet', 'level'], 'gt')])
    })
    test('filter param choice (wavelet zz)', () => {
      const f = setFilter(base(), 'Wavelet', { enabled: true, params: { wavelet: 'zz' } })
      expect(brief(run(f))).toEqual([err('constraint', ['image_types', 'Wavelet', 'wavelet'], 'choice')])
    })
    test('nullable options accept null', () => {
      expect(run(setOption(base(), 'minimumROISize', null))).toEqual([])
      expect(run(setOption(base(), 'weightingNorm', null))).toEqual([])
    })
    test('params of a disabled filter are not checked', () => {
      const f = setFilter(base(), 'Wavelet', { enabled: false, params: { level: 0, wavelet: 'zz' } })
      expect(run(f)).toEqual([])
    })
  })
})

describe('helpers', () => {
  test('fieldOf drops list indexes', () => {
    expect(fieldOf(['settings', 'binWidth'])).toBe('settings.binWidth')
    expect(fieldOf(['image_types', 'LoG', 'sigma'])).toBe('image_types.LoG.sigma')
    expect(fieldOf(['settings', 'resampledPixelSpacing', 1])).toBe('settings.resampledPixelSpacing')
    expect(fieldOf(['features'])).toBe('features')
  })

  test('hasErrors ignores warnings', () => {
    const w: Issue = { loc: ['settings', 'normalize'], rule: 'normalize_hu', severity: 'warning' }
    const e: Issue = { loc: ['features'], rule: 'nothing', severity: 'error' }
    expect(hasErrors([])).toBe(false)
    expect(hasErrors([w])).toBe(false)
    expect(hasErrors([w, e])).toBe(true)
  })

  test('fromServer keeps loc/rule/severity/msg and has no key', () => {
    const s: ServerIssue = { loc: ['settings', 'binWidth'], rule: 'bin_xor', severity: 'error', msg: 'Choose bin width or bin count' }
    const i = fromServer(s)
    expect(i).toEqual({ loc: ['settings', 'binWidth'], rule: 'bin_xor', severity: 'error', msg: 'Choose bin width or bin count' })
    expect(i.key).toBeUndefined()
    expect(fieldOf(i.loc)).toBe('settings.binWidth')
  })
})
