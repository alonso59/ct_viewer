// AUD-A2-13 (DCM-06): storage in the unit that fits, never "1 MB" for 3 KB.
import { featureUnit, fmtBytes, fmtColumn, fmtNum, fmtValue, midEllipsis, parseNum } from './format'

test('bytes use the unit that fits', () => {
  expect(fmtBytes(3024)).toBe('3 KB')
  expect(fmtBytes(512)).toBe('512 B')
  expect(fmtBytes(2_400_000)).toBe('2.4 MB')
  expect(fmtBytes(1.25e9)).toBe('1.3 GB')
  expect(fmtBytes(null)).toBe('—')
})

// AUD-A3-04 (owner 2026-09-25): English format everywhere; inputs accept `,` and `.`
test('numbers use a point and no thousands separator in measured values', () => {
  expect(fmtNum(117583)).toBe('117583')
  expect(fmtNum(0.9312)).toBe('0.93')
  expect(parseNum('3,5')).toBe(3.5)
  expect(parseNum(' 3.5 ')).toBe(3.5)
  expect(parseNum('-0,25')).toBe(-0.25)
  expect(parseNum('1e5')).toBe(100000)
  expect(parseNum('3,5,1')).toBeNull()
  expect(parseNum('abc')).toBeNull()
  expect(parseNum('')).toBeNull()
})

// AUD-A3-15 (DB-03, UI-14): 3 significant digits; scientific above 1e5 for the whole column; units
test('feature values have a consistent precision and a unit', () => {
  expect(fmtValue(0.93124)).toBe('0.931')
  expect(fmtValue(1847.2)).toBe('1847')
  expect(fmtValue(117583)).toBe('1.18e5')
  expect(fmtValue(0.00012)).toBe('1.20e-4')
  expect(fmtValue(null)).toBe('—')
  const col = fmtColumn([117583, 0.93, 1847])
  expect([117583, 0.93, 1847].map(col)).toEqual(['1.18e5', '9.30e-1', '1.85e3'])
  expect([9.1, 11.4].map(fmtColumn([9.1, 11.4]))).toEqual(['9.1', '11.4'])
  expect(featureUnit('original_shape_MeshVolume')).toBe('mm³')
  expect(featureUnit('original_shape_SurfaceArea')).toBe('mm²')
  expect(featureUnit('original_shape_Maximum3DDiameter')).toBe('mm')
  expect(featureUnit('original_shape_Sphericity')).toBe('')
  expect(featureUnit('original_firstorder_Mean')).toBe('HU')
  expect(featureUnit('original_firstorder_Mean', 'MR')).toBe('')
  expect(featureUnit('wavelet-LLH_firstorder_Mean')).toBe('')
  expect(featureUnit('original_glcm_Contrast')).toBe('')
})

// AUD-A3-13: paths keep both ends
test('middle ellipsis keeps the file name', () => {
  const p = '/data/shared/Dataset900/nifti/01_case_00001_0000.nii.gz'
  const m = midEllipsis(p, 40)
  expect(m.length).toBeLessThanOrEqual(40)
  expect(m).toContain('…')
  expect(m.endsWith('01_case_00001_0000.nii.gz')).toBe(true)
  expect(midEllipsis('/short', 40)).toBe('/short')
})
