// PRJ-18 label imports: Slicer .ctbl, ITK-SNAP label descriptions, nnU-Net dataset.json.
import { detectKind, mergeLabels, parseItkSnap, parseLabelFile, parseNnunet, parseSlicer } from './labelFiles'

test('3D Slicer colour table', () => {
  const text = '# Color table file\n# 3 values\n0 Background 0 0 0 0\n1 kidney 0 255 255 255\n2 tumor 255 255 0 128\n'
  expect(parseSlicer(text)).toEqual([
    { value: 1, name: 'kidney', color: '#00FFFF', opacity: 0.3, visible: true },
    { value: 2, name: 'tumor', color: '#FFFF00', opacity: expect.closeTo(0.15, 2), visible: true },
  ])
})

test('ITK-SNAP label description', () => {
  const text = '################################################\n    0     0    0    0        0  0  0    "Clear Label"\n    1   255    0    0        1  1  1    "Label 1"\n    2     0  255    0        1  0  1    "Liver"\n'
  const labels = parseItkSnap(text)
  expect(labels.map((l) => [l.value, l.name, l.color, l.visible])).toEqual([
    [1, 'Label 1', '#FF0000', true],
    [2, 'Liver', '#00FF00', false],
  ])
})

test('nnU-Net dataset.json v2 and v1', () => {
  const v2 = JSON.stringify({ labels: { background: 0, kidney: 1, tumor: 2, both: [1, 2] } })
  expect(parseNnunet(v2).map((l) => [l.value, l.name])).toEqual([[1, 'kidney'], [2, 'tumor']])
  const v1 = JSON.stringify({ labels: { '0': 'background', '1': 'liver', '2': 'lesion' } })
  expect(parseNnunet(v1).map((l) => [l.value, l.name])).toEqual([[1, 'liver'], [2, 'lesion']])
})

test('detects the format and merges by value without deleting', () => {
  expect(detectKind('dataset.json', '{}')).toBe('nnunet')
  expect(detectKind('labels.txt', '    1   255 0 0   1 1 1 "A"')).toBe('itksnap')
  expect(detectKind('x.ctbl', '1 kidney 0 255 255 255')).toBe('slicer')
  expect(() => parseLabelFile('x.bin', 'garbage')).toThrow('unrecognized')
  const merged = mergeLabels(
    [{ value: 1, name: 'label_1', color: '#FFFFFF', opacity: 0.2, visible: true }, { value: 5, name: 'label_5', color: '#FFFFFF', opacity: 0.2, visible: true }],
    parseLabelFile('d.json', JSON.stringify({ labels: { kidney: 1, tumor: 2 } })).labels,
  )
  expect(merged.map((l) => l.name)).toEqual(['kidney', 'tumor', 'label_5'])
})

test('project catalogs retain label values, names, colors and display defaults on reimport', () => {
  const catalog = [{ value: 17, name: 'Reviewed structure', color: '#12abef', opacity: 0.45, visible: false }]
  for (const doc of [catalog, { label_map: catalog }]) {
    const parsed = parseLabelFile('catalog.json', JSON.stringify(doc))
    expect(parsed.kind).toBe('project')
    expect(parsed.labels).toEqual([{ ...catalog[0], color: '#12ABEF' }])
  }
})

test.each([
  [{ value: 1, name: 'A', color: '#112233' }, { value: 1, name: 'B', color: '#445566' }],
  [{ value: 70000, name: 'A', color: '#112233' }],
  [{ value: 1, name: 'A', color: 'red' }],
  [{ value: 1, name: 'A', color: '#112233', opacity: 2 }],
  [{ value: 1, name: 'A', color: '#112233', visible: 'yes' }],
].map((catalog) => ({ catalog })))('invalid catalogs cannot change the label draft: $catalog', ({ catalog }) => {
  expect(() => parseLabelFile('catalog.json', JSON.stringify(catalog))).toThrow()
})
