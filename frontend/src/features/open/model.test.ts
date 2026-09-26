// Open-mode records through the viewer's item shape (SRC-09, VW-05/21).
import type { OpenItem } from '../../api'
import { attachStart, attachedTo, autoLabels, importSource, toItemRecord } from './model'

const item = (over: Partial<OpenItem>): OpenItem => ({
  n: 0, item_id: 'open.0', name: 'a.nii.gz', rel: 'a.nii.gz', format: 'nifti', kind: 'image',
  geometry: { shape: [8, 9, 5], spacing: [1, 1, 2], dtype: 'int16', orientation: 'RAS', affine: null },
  modality: null, n_slices: 5, attached_to: null, axis_order: null, needs_axis_order: false, error: null, ...over,
})

test('unknown modality uses percentiles (not CT presets); only an attached segmentation overlays (SRC-10)', () => {
  const r = toItemRecord(item({}), null)
  expect(r.modality).toBeNull()
  expect(r.mask).toBeNull()
  const withMask = toItemRecord(item({}), item({ n: 1, rel: 'm.nii.gz', kind: 'label', attached_to: 0 }))
  expect(withMask.masks.open?.ref).toBe('m.nii.gz')
})

test('the last attached label wins; auto labels are label_{value}', () => {
  const items = [item({}), item({ n: 1, attached_to: 0 }), item({ n: 2, attached_to: 0 })]
  expect(attachedTo(items, 0)?.n).toBe(2)
  expect(autoLabels(3).map((l) => l.name)).toEqual(['label_1', 'label_2', 'label_3'])
})

test('an attached mask from a sibling folder travels into the import (SRC-05/15, ADR-0027, AUD-A2-12)', () => {
  const s = { root: '/data/ds/nifti' }
  const img = { rel: '01_case_00001_0000.nii.gz', format: 'nifti' as const }
  expect(importSource(s, img, null, '/data/ds/nifti/01_case_00001_0000.nii.gz')).toEqual({ path: '/data/ds/nifti/01_case_00001_0000.nii.gz' })
  expect(importSource(s, img, { rel: '/data/ds/seg/01_case_00001.nii.gz' }, '/x')).toEqual({
    path: '/data/ds',
    adapter: 'nifti-files',
    options: { include: ['nifti/01_case_00001_0000.nii.gz', 'seg/01_case_00001.nii.gz'], masks: { 'nifti/01_case_00001_0000.nii.gz': 'seg/01_case_00001.nii.gz' } },
  })
  // a DICOM item goes through the converter: no mask to carry
  expect(importSource(s, { rel: 'a.dcm', format: 'dicom' }, { rel: 'm.nii.gz' }, '/p')).toEqual({ path: '/p' })
})

test('the attach browser starts in a mask folder next to the images (SRC-10, AUD-A2-03)', () => {
  expect(attachStart('/d/ds/nifti', [], ['nifti', 'seg', 'voi'])).toBe('/d/ds/seg')
  expect(attachStart('/d/nn/imagesTr', [], ['imagesTr', 'labelsTr'])).toBe('/d/nn/labelsTr')
  expect(attachStart('/d/ds', ['nifti', 'seg'], ['ds'])).toBe('/d/ds/seg')
  expect(attachStart('/d/x', ['a'], ['x', 'y'])).toBe('/d/x')
})
