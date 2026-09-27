// @vitest-environment jsdom
// AUD-A1-07 (UI-05): palette ranking on the real command set
import i18n from '../i18n'
import { bootstrap } from '../app/bootstrap'
import { commandTitle } from './keybindings'
import { paletteScore } from './paletteMatch'
import { registry } from './registry'

const rank = (q: string) =>
  [...registry.commands.values()]
    .filter((c) => registry.available(c, 'project'))
    .map((c) => ({ id: c.id, s: paletteScore(q, commandTitle(c, i18n.t), (c.keywords ?? []).map((k) => i18n.t(k)), c.category ? i18n.t(c.category) : '') }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s)
    .map((x) => x.id)

test('prefix and word matches beat scattered letters', () => {
  expect(paletteScore('fit', 'Fit view')).toBeGreaterThan(paletteScore('fit', 'Open file or folder…'))
  expect(paletteScore('reject', 'Rejected')).toBeGreaterThan(paletteScore('reject', 'Project settings', [], 'Project'))
  expect(paletteScore('zz', 'Fit view')).toBe(0)
  expect(paletteScore('next case', 'Next case')).toBe(1)
  expect(paletteScore('case next', 'Next case')).toBeGreaterThan(0.5)
})

test('the audit queries find their command first', () => {
  bootstrap()
  expect(rank('share').slice(0, 2).sort()).toEqual(['project.copyEditLink', 'project.copyViewLink'])
  expect(rank('reject')[0]).toBe('curation.reject')
  expect(rank('fit')[0]).toBe('viewer.fit')
  expect(rank('dashboard')).toEqual(expect.arrayContaining(['dashboard.openLatest', 'view.show.dashboards']))
  expect(rank('dataset')).toEqual(expect.arrayContaining(['project.exportDataset.csv', 'project.exportDataset.jsonl']))
  expect(rank('segmentation')[0]).toBe('viewer.nextSegSet')
  expect(rank('unreviewed')[0]).toBe('explorer.nextUnreviewed')
  expect(rank('image')).toContain('view.show.image')
})
