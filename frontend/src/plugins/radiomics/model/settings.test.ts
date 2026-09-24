// RAD-01/02/03 schema-driven form model
import schemaJson from './fixtures/schema.json'
import {
  defaultFeatures,
  defaultForm,
  featureCount,
  fromWire,
  isSelectable,
  optionsByGroup,
  parseList,
  setFeatures,
  setFilter,
  setOption,
  toWire,
} from './settings'
import type { SettingsSchema, WireSettings } from './types'

const schema = schemaJson as unknown as SettingsSchema
const cls = (name: string) => {
  const c = schema.feature_classes.find((x) => x.name === name)
  if (!c) throw new Error(name)
  return c
}

describe('defaultForm (engine defaults)', () => {
  const form = defaultForm(schema)

  test('only Original is enabled', () => {
    const on = Object.entries(form.filters).filter(([, s]) => s.enabled).map(([n]) => n)
    expect(on).toEqual(['Original'])
    expect(Object.keys(form.filters).sort()).toEqual(schema.filters.map((f) => f.name).sort())
  })

  test('disabled filters carry their param defaults', () => {
    expect(form.filters.Wavelet?.params).toMatchObject({ wavelet: 'coif1', level: 1, start_level: 0 })
    expect(form.filters.LoG?.params.sigma).toEqual([])
    expect(form.filters.Original?.params).toEqual({})
  })

  test('options show engine defaults', () => {
    expect(form.options.binWidth).toBe(25)
    expect(form.options.binCount).toBeNull()
    expect(form.options.force2D).toBe(false)
    expect(form.options.interpolator).toBe('sitkBSpline')
    expect(form.options.distances).toEqual([1])
    expect(Object.keys(form.options)).toEqual(schema.options.map((o) => o.name))
  })

  test('features = schema defaults; shape2D off; deprecated off', () => {
    expect(form.features.shape2D).toEqual([])
    for (const c of schema.feature_classes) {
      expect(form.features[c.name]).toEqual(schema.defaults.features?.[c.name] ?? [])
      const deprecated = c.features.filter((f) => f.deprecated).map((f) => f.name)
      for (const d of deprecated) expect(form.features[c.name]).not.toContain(d)
    }
    expect(form.features.firstorder).not.toContain('StandardDeviation')
    expect(form.features.glcm).not.toContain('SumVariance')
    expect(featureCount(form)).toBe(Object.values(schema.defaults.features ?? {}).reduce((n, l) => n + (l?.length ?? 0), 0))
  })

  test('defaultFeatures is the default-enabled set', () => {
    expect(defaultFeatures(cls('shape2D'))).not.toContain('SphericalDisproportion')
    expect(defaultFeatures(cls('firstorder'))).toEqual(schema.defaults.features?.firstorder)
  })
})

describe('toWire / fromWire', () => {
  test('toWire(defaultForm) equals schema.defaults', () => {
    const w = toWire(schema, defaultForm(schema))
    expect(w.image_types).toEqual(schema.defaults.image_types)
    expect(w.features).toEqual(schema.defaults.features)
    const s = schema.defaults.settings ?? {}
    expect(Object.keys(w.settings ?? {}).sort()).toEqual(Object.keys(s).sort())
    for (const [k, v] of Object.entries(s)) expect(w.settings?.[k]).toEqual(v)
  })

  test('round-trips a modified form', () => {
    let f = defaultForm(schema)
    f = setFilter(f, 'LoG', { enabled: true, params: { sigma: [1, 2.5] } })
    f = setFilter(f, 'Wavelet', { enabled: true, params: { wavelet: 'haar', level: 2 } })
    f = setFilter(f, 'Original', { enabled: false })
    f = setFeatures(f, 'glcm', [])
    f = setFeatures(f, 'shape2D', ['Perimeter', 'Elongation'])
    f = setOption(setOption(f, 'binWidth', null), 'binCount', 32)
    f = setOption(f, 'force2D', true)
    f = setOption(f, 'resampledPixelSpacing', [1, 1, 0])
    const w = toWire(schema, f)
    expect(Object.keys(w.image_types ?? {}).sort()).toEqual(['LoG', 'Wavelet'])
    expect(w.features?.glcm).toBeUndefined()
    const back = fromWire(schema, w)
    expect(toWire(schema, back)).toEqual(w)
    expect(back.filters.Original?.enabled).toBe(false)
    expect(back.filters.Wavelet?.params).toMatchObject({ wavelet: 'haar', level: 2 })
    expect(back.features.glcm).toEqual([])
    expect(back.features.shape2D).toEqual(['Elongation', 'Perimeter'])
    expect(back.options.binCount).toBe(32)
    expect(back.options.resampledPixelSpacing).toEqual([1, 1, 0])
  })

  test('feature order follows the engine regardless of selection order', () => {
    const a = setFeatures(defaultForm(schema), 'ngtdm', ['Strength', 'Busyness', 'Contrast'])
    const b = setFeatures(defaultForm(schema), 'ngtdm', ['Contrast', 'Strength', 'Busyness'])
    expect(toWire(schema, a).features?.ngtdm).toEqual(['Busyness', 'Contrast', 'Strength'])
    expect(toWire(schema, a)).toEqual(toWire(schema, b))
  })

  test('features {cls: null} means the default-enabled features', () => {
    const wire = { image_types: { Original: {} }, features: { shape2D: null, glcm: null }, settings: {} } as unknown as WireSettings
    const f = fromWire(schema, wire)
    expect(f.features.shape2D).toEqual(defaultFeatures(cls('shape2D')))
    expect(f.features.glcm).toEqual(defaultFeatures(cls('glcm')))
    expect(f.features.firstorder).toEqual([])
  })

  test('missing settings fall back to schema defaults', () => {
    const f = fromWire(schema, { image_types: { Original: {} }, features: { firstorder: ['Mean'] }, settings: { binWidth: 10 } } as WireSettings)
    expect(f.options.binWidth).toBe(10)
    expect(f.options.interpolator).toBe('sitkBSpline')
  })
})

describe('parseList', () => {
  test.each<[string, boolean, number[] | null]>([
    ['', false, null],
    ['   ', true, null],
    ['1, 2.5 3', false, [1, 2.5, 3]],
    ['1;2;3', true, [1, 2, 3]],
    ['1,,2', true, [1, 2]],
    [' 0.5 ', false, [0.5]],
  ])('%j (int=%s)', (text, int, expected) => {
    expect(parseList(text, int)).toEqual(expected)
  })

  test('non-numbers become NaN (caught by validation)', () => {
    expect(parseList('a', false)?.[0]).toBeNaN()
    expect(parseList('1.5', true)).toEqual([1.5])
  })
})

describe('optionsByGroup / helpers', () => {
  test('keeps schema group order and covers every option', () => {
    const g = optionsByGroup(schema)
    expect([...g.keys()]).toEqual(schema.groups.map((x) => x.id))
    expect(g.get('discretization')?.map((o) => o.name)).toEqual(['binWidth', 'binCount'])
    expect([...g.values()].flat().length).toBe(schema.options.length)
  })

  test('isSelectable follows availability', () => {
    const byName = Object.fromEntries(schema.filters.map((f) => [f.name, isSelectable(f)]))
    expect(byName.LBP3D).toBe(false)
    expect(byName.Original).toBe(true)
  })

  test('setters are immutable', () => {
    const f = defaultForm(schema)
    const g = setOption(setFilter(setFeatures(f, 'glcm', []), 'LoG', { enabled: true }), 'binWidth', 5)
    expect(f.options.binWidth).toBe(25)
    expect(f.filters.LoG?.enabled).toBe(false)
    expect(f.features.glcm?.length).toBeGreaterThan(0)
    expect(g.filters.LoG?.params.sigma).toEqual([])
  })
})
