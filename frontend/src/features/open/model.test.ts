// Open-mode records through the viewer's item shape (SRC-09, VW-05/21).
import type { OpenItem } from '../../api'
import { attachedTo, autoLabels, toItemRecord } from './model'

const item = (over: Partial<OpenItem>): OpenItem => ({
  n: 0, item_id: 'open.0', name: 'a.nii.gz', rel: 'a.nii.gz', format: 'nifti', kind: 'image',
  geometry: { shape: [8, 9, 5], spacing: [1, 1, 2], dtype: 'int16', orientation: 'RAS', affine: null },
  modality: null, n_slices: 5, attached_to: null, axis_order: null, needs_axis_order: false, error: null, ...over,
})

test('unknown modality uses percentiles (not CT presets); a label alone overlays itself', () => {
  const r = toItemRecord(item({}), null)
  expect(r.modality).toBeNull()
  expect(r.mask).toBeNull()
  const l = toItemRecord(item({ kind: 'label' }), null)
  expect(l.mask?.ref).toBe('a.nii.gz')
  const withMask = toItemRecord(item({}), item({ n: 1, rel: 'm.nii.gz', kind: 'label', attached_to: 0 }))
  expect(withMask.masks.open?.ref).toBe('m.nii.gz')
})

test('the last attached label wins; auto labels are label_{value}', () => {
  const items = [item({}), item({ n: 1, attached_to: 0 }), item({ n: 2, attached_to: 0 })]
  expect(attachedTo(items, 0)?.n).toBe(2)
  expect(autoLabels(3).map((l) => l.name)).toEqual(['label_1', 'label_2', 'label_3'])
})
