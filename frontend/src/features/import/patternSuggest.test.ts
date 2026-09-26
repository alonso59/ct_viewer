// SRC-17: candidates come from the sampled names only, and only with groups the sample supports.
import { CONVERTER_PATTERN, converterPattern, sampleStems, segments, suggestPatterns, toJsRegex } from './patternSuggest'

test('stems: accepted extensions only, masks left out', () => {
  expect(sampleStems(['a_case_1_0000.nii.gz', 'b.nii', 'c.npy', 'd_seg.nii.gz', 'e_mask.nii', 'notes.txt'])).toEqual(['a_case_1_0000', 'b', 'c'])
})

test('case literal and 4-digit channel: best candidate names both, as a Python pattern', () => {
  const stems = ['kits_case_00042_0000', 'kits_case_00043_0000', 'kits_case_00044_0000']
  const [best] = suggestPatterns(stems)
  expect(best?.groups).toEqual(['case_id', 'channel'])
  expect(best?.pattern).toContain('(?P<case_id>')
  expect(best?.matched).toBe(3)
  expect(toJsRegex(best?.pattern ?? '').exec('kits_case_00042_0000')?.groups).toEqual({ case_id: 'case_00042', channel: '0000' })
})

test('leading short number as scan_idx and a trailing L/R side, only when present', () => {
  const [best] = suggestPatterns(['01_case_7_L', '02_case_7_R', '01_case_8_L'])
  expect(best?.groups).toEqual(['scan_idx', 'case_id', 'side'])
  expect(suggestPatterns(['case_1_0000', 'case_2_0000']).flatMap((c) => c.groups)).not.toContain('side')
})

test('no structure, no sample, or a minority match: no guess', () => {
  expect(suggestPatterns([])).toEqual([])
  expect(suggestPatterns(['liver', 'spleen', 'kidney'])).toEqual([])
  // only one of four names has a channel token: below half, not proposed
  expect(suggestPatterns(['a', 'b', 'c', 'd_0000'])).toEqual([])
})

test('without a case literal the channel still splits off the case id', () => {
  const [best] = suggestPatterns(['patientA_0000', 'patientB_0000'])
  expect(best?.groups).toEqual(['case_id', 'channel'])
  expect(toJsRegex(best?.pattern ?? '').exec('patientA_0000')?.groups?.case_id).toBe('patientA')
})

test('segments mark each named group in the stem', () => {
  const [best] = suggestPatterns(['x_case_1_0000', 'x_case_2_0000'])
  expect(segments(best?.pattern ?? '', 'x_case_1_0000')).toEqual([
    { text: 'x_' },
    { text: 'case_1', group: 'case_id' },
    { text: '_' },
    { text: '0000', group: 'channel' },
  ])
})

test('the converter naming is pre-filled only when every stem follows it (ADR-0027, AUD-A2-12)', () => {
  expect(converterPattern(['01_case_00030_0000'])).toBe(CONVERTER_PATTERN)
  expect(toJsRegex(CONVERTER_PATTERN).exec('01_case_00030_0000')?.groups).toMatchObject({ scan_idx: '01', case_id: 'case_00030', channel: '0000' })
  expect(toJsRegex(CONVERTER_PATTERN).exec('02_CT_case_00031_0000')?.groups).toMatchObject({ scan_idx: '02', modality: 'CT', case_id: 'case_00031' })
  expect(converterPattern(['01_case_00030_0000', 'loose scan'])).toBeNull()
  expect(converterPattern([])).toBeNull()
})
