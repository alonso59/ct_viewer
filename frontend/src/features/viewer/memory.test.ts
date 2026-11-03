// @vitest-environment jsdom
// UI-13 (VW-05, VW-15): each project item's last view is kept across reloads, at most
// MAX_REMEMBERED items; the item viewed longest ago is forgotten first.
import { MAX_REMEMBERED, useItemMemory, type ItemView } from './memory'

const view = (ww: number): ItemView => ({ ww, wl: 50, ras: [1, 2, 3], labels: { 1: false } })

test('a full memory forgets the item viewed longest ago; a revisit makes an item the newest', () => {
  const { remember } = useItemMemory.getState()
  for (let i = 0; i < MAX_REMEMBERED; i++) remember(`p|item${i}`, view(i + 1))
  remember('p|item0', view(1500))
  remember('p|new', view(400))
  const { items, order } = useItemMemory.getState()
  expect(order).toHaveLength(MAX_REMEMBERED)
  expect(items['p|item1']).toBeUndefined()
  expect(items['p|item0']?.ww).toBe(1500)
  expect(order.slice(-2)).toEqual(['p|item0', 'p|new'])
  const saved = JSON.parse(localStorage.getItem('rw.viewer.items') ?? '{}') as { state: { items: Record<string, ItemView> } }
  expect(saved.state.items['p|new']).toEqual(view(400))
})
