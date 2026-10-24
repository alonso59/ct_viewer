// SRC-17 pattern by example: roles on one real path → the pattern; a picked mask → the template.
import { buildPattern, defaultRole, matches, pairedFolders, rolesFrom, templatedMasks, templateFrom, tokenize, type Role } from './byExample'
import { FOLDER_PATTERN, toJsRegex } from './patternSuggest'

const roles = (path: string, set: Record<string, Role>) => tokenize(path).map((t) => set[t.text] ?? defaultRole(t))

test('tokens: folders whole, the file name split on _ - .', () => {
  expect(tokenize('ImageTr/P_001/ct').map((t) => [t.text, t.folder, t.sep, t.at])).toEqual([
    ['ImageTr', true, '/', 0],
    ['P_001', true, '/', 8],
    ['ct', false, '', 14],
  ])
  expect(tokenize('case_00012-L').map((t) => t.text + t.sep)).toEqual(['case_', '00012-', 'L'])
})

test('a case folder (PanTS): the folders stay, the file name is fixed text', () => {
  const p = 'ImageTr/P_001/ct'
  const rx = buildPattern(tokenize(p), roles(p, { ImageTr: 'fixed', P_001: 'case_id' }))
  expect(rx).toBe('^ImageTr/(?P<case_id>[^/]+)/ct$')
  expect(toJsRegex(rx ?? '').exec('ImageTr/PanTS_00000042/ct')?.groups?.case_id).toBe('PanTS_00000042')
  expect(matches(rx ?? '', 'LabelTr/P_001/segmentations/liver')).toBe(false)
})

test('name tokens: neighbours join one group, side and channel have their shapes, no case → null', () => {
  const p = 'kits/case_00012_L_0000'
  const tokens = tokenize(p)
  expect(buildPattern(tokens, roles(p, {}))).toBeNull()
  const rx = buildPattern(tokens, roles(p, { case: 'case_id', '00012': 'case_id', L: 'side', '0000': 'channel' }))
  // every folder is "any": the pattern is on the file name only
  expect(rx).toBe('^(?P<case_id>[A-Za-z]+_\\d+)_(?P<side>[LR])_(?P<channel>\\d{4})$')
  expect(toJsRegex(rx ?? '').exec('case_00099_R_0000')?.groups).toEqual({ case_id: 'case_00099', side: 'R', channel: '0000' })
  // a group again further on is "any" (a Python group name is used once)
  expect(buildPattern(tokenize('a_1_b'), ['case_id', 'fixed', 'case_id'])).toBe('^(?P<case_id>[A-Za-z]+)_1_[A-Za-z]+$')
})

test('roles from a pattern: the prefilled folder pattern marks the case folder', () => {
  const p = 'ImageTr/P_001/ct'
  expect(rolesFrom(FOLDER_PATTERN, p, tokenize(p))).toEqual(['any', 'case_id', 'fixed'])
  expect(rolesFrom('^(?P<case_id>case_\\d+)_0000$', 'x/case_1_0000', tokenize('x/case_1_0000'))).toEqual(['any', 'case_id', 'case_id', 'fixed'])
  expect(rolesFrom(undefined, p, tokenize(p))).toEqual(['any', 'any', 'fixed'])
  expect(rolesFrom('(', p, tokenize(p))).toEqual(['any', 'any', 'fixed']) // invalid regex: defaults
})

test('the mask template comes from the mask picked for the example', () => {
  const rx = '^ImageTr/(?P<case_id>[^/]+)/ct$'
  expect(templateFrom(rx, 'ImageTr/P_001/ct', 'LabelTr/P_001/segmentations')).toBe('LabelTr/{case_id}/segmentations')
  expect(templateFrom('^(?P<case_id>case_\\d+)_(?P<channel>\\d{4})$', 'img/case_7_0000', 'lbl/case_7.nii.gz')).toBe('lbl/{case_id}.nii.gz')
  expect(templateFrom(rx, 'ImageTr/P_001/ct', 'labels/all.nii.gz')).toBeNull() // the same mask for every image
  const paths = ['ImageTr/P_001/ct', 'LabelTr/P_001/segmentations/liver', 'LabelTr/P_002/segmentations/liver']
  expect([...templatedMasks(rx, 'LabelTr/{case_id}/segmentations', paths)]).toEqual(['LabelTr/P_001/segmentations', 'LabelTr/P_001/segmentations/liver'])
})

test('paired image and label folders fill the pattern and the template', () => {
  expect(pairedFolders(['ImageTr/P_1/ct.nii.gz', 'ImageTr/P_2/ct.nii.gz', 'LabelTr/P_1/segmentations/liver.nii.gz', 'LabelTr/P_9/segmentations/pancreas.nii.gz'])).toEqual({
    pattern: '^ImageTr/(?P<case_id>[^/]+)/ct$',
    mask_template: 'LabelTr/{case_id}/segmentations',
  })
  expect(pairedFolders(['data/imagesTr/case_1_0000.nii.gz', 'data/labelsTr/case_1.nii.gz'])).toEqual({
    pattern: '^data/imagesTr/(?P<case_id>[^/]+?)_(?P<channel>\\d{4})$',
    mask_template: 'data/labelsTr/{case_id}.nii.gz',
  })
  expect(pairedFolders(['ImageTr/P_1/ct.nii.gz', 'LabelTr/P_1/mask.nii.gz'])?.mask_template).toBe('LabelTr/{case_id}/mask.nii.gz')
  // images only, unrelated folders, or a train/test mismatch: no guess
  expect(pairedFolders(['ImageTr/P_1/ct.nii.gz', 'ImageTr/P_2/ct.nii.gz'])).toBeNull()
  expect(pairedFolders(['a/x.nii.gz', 'b/y.nii.gz'])).toBeNull()
  expect(pairedFolders(['imagesTr/a.nii.gz', 'labelsTs/a.nii.gz'])).toBeNull()
})
