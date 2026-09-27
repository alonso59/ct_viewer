// IMP-01..05 / SRC-04/15/17 (AUD-A6-07): the import wizard's rules without the component: where it
// starts, the alias check, the adapter choice, when Next is enabled and what it does, the counts.
import { expect, test } from 'vitest'

import type { DetectCandidate, ImportPreview } from '../../api'
import { aliasProblem, autoPattern, canNext, cleanAlias, firstAdapter, imageStems, initialState, jobFailed, nextAction, previewCounts, type NextInput } from './model'

const cand = (adapter: string, available = true): DetectCandidate => ({ adapter, available, reason: '', counts: { nifti: 0, dicom: 0, npy: 0, ignored: 0 }, confidence: 'high', options: {}, unavailable_reason: null }) as DetectCandidate

test('a prefill (Create project from this) starts at detection; a file keeps its folder', () => {
  expect(initialState(null)).toEqual({ step: 'root', dir: null, file: null })
  expect(initialState({ path: '/data/ds/img_0000.nii.gz' })).toEqual({ step: 'detect', dir: '/data/ds', file: '/data/ds/img_0000.nii.gz' })
  expect(initialState({ path: '/data/ds' })).toEqual({ step: 'detect', dir: '/data/ds', file: null })
})

test('IMP-14 alias: format, and a taken alias pointing elsewhere (unless SRC-15 add)', () => {
  expect(cleanAlias('data-2 x')).toBe('DATA2X')
  expect(aliasProblem('data', undefined, false, '/x')).toBe('invalid')
  expect(aliasProblem('2DATA', undefined, false, '/x')).toBe('invalid')
  expect(aliasProblem('DATA', undefined, false, '/x')).toBeNull()
  expect(aliasProblem('DATA', { path: '/x/' }, false, '/x')).toBeNull() // same root: a re-import
  expect(aliasProblem('DATA', { path: '/other' }, false, '/x')).toBe('taken')
  expect(aliasProblem('DATA', { path: '/other' }, true, '/x')).toBeNull()
})

test('the adapter after detection: the prefill, else the first importable, else any available', () => {
  const cands = [cand('open'), cand('dicom.convert', false), cand('nifti-files'), cand('metadata-v1')]
  expect(firstAdapter(cands)).toBe('nifti-files')
  expect(firstAdapter(cands, 'metadata-v1')).toBe('metadata-v1')
  expect(firstAdapter(cands, 'dicom.convert')).toBe('open') // wanted but unavailable
  expect(firstAdapter([cand('open')])).toBe('open')
  expect(firstAdapter([cand('nifti-files', false)])).toBeNull()
})

test('image names: an include list without its masks, one file, or the folder; the converter naming prefills', () => {
  expect(imageStems({ include: ['a/01_case_00001_0000.nii.gz', 'seg/m.nii.gz'], masks: { imported: 'seg/m.nii.gz' } }, null, ['x.nii.gz'])).toEqual(['01_case_00001_0000'])
  expect(imageStems({}, '/d/b_0000.nii.gz', ['x.nii.gz'])).toEqual(['b_0000'])
  const stems = imageStems({}, null, ['01_case_00001_0000.nii.gz', '02_case_00001_0000.nii.gz'])
  expect(autoPattern('nifti-files', false, {}, stems)).not.toBeNull()
  expect(autoPattern('nifti-files', true, {}, stems)).toBeNull() // the user edited the options
  expect(autoPattern('metadata-v1', false, {}, stems)).toBeNull()
  expect(autoPattern('nifti-files', false, { pattern: 'x' }, stems)).toBeNull()
})

const base: NextInput = { step: 'root', path: '/data/ds', aliasOk: true, upload: false, hasUploadedMetadata: false, adapter: null, previewPending: false, preview: undefined, commitPending: false }
const preview = (kinds: string[]) => ({ files: kinds.map((kind) => ({ kind })), counts: { scan_rows: 24, cases: 8, voi_rows: 10, excluded_upstream: 1 } }) as unknown as ImportPreview

test('Next: enabled per step, and what it does', () => {
  expect(canNext(base)).toBe(true)
  expect(canNext({ ...base, path: null })).toBe(false)
  expect(canNext({ ...base, aliasOk: false })).toBe(false)
  expect(canNext({ ...base, upload: true })).toBe(false) // upload without metadata.jsonl
  expect(canNext({ ...base, upload: true, hasUploadedMetadata: true })).toBe(true)
  const detect = { ...base, step: 'detect' as const }
  expect(canNext({ ...detect, adapter: null })).toBe(false)
  for (const a of ['open', 'dicom.convert', 'nifti-files', 'metadata-v1']) expect(canNext({ ...detect, adapter: a })).toBe(true)
  expect(canNext({ ...detect, adapter: 'numpy' })).toBe(false)
  expect(canNext({ ...detect, adapter: 'nifti-files', previewPending: true })).toBe(false)
  const prev = { ...base, step: 'preview' as const }
  expect(canNext({ ...prev, preview: preview(['phase']) })).toBe(false) // IMP-04: no metadata, no commit
  expect(canNext({ ...prev, preview: preview(['metadata']) })).toBe(true)
  expect(canNext({ ...prev, preview: preview(['metadata']), commitPending: true })).toBe(false)
  expect(canNext({ ...base, step: 'index' })).toBe(false)
  expect(nextAction('root', null, true)).toBe('upload-preview')
  expect(nextAction('root', null, false)).toBe('detect')
  expect(nextAction('detect', 'open', false)).toBe('open')
  expect(nextAction('detect', 'dicom.convert', false)).toBe('convert')
  expect(nextAction('detect', 'nifti-files', false)).toBe('preview')
  expect(nextAction('preview', 'nifti-files', false)).toBe('commit')
  expect(nextAction('index', null, false)).toBeNull()
})

test('the preview counts and a failed job', () => {
  expect(previewCounts(preview(['metadata'])).map((c) => c.n)).toEqual([24, 8, 10, 1])
  expect(['failed', 'cancelled', 'interrupted'].every((s) => jobFailed(s as never))).toBe(true)
  expect(jobFailed('succeeded')).toBe(false)
  expect(jobFailed(undefined)).toBe(false)
})
