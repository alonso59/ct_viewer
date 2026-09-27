// @vitest-environment jsdom
// UI-13 / UI-14 (AUD-A3-01, AUD-A1-18): the bottom panel follows the active editor type; a case
// tab keeps it closed until a panel tab has content for its item; the default height is ≤ 20 %.
import { panelAutoHeight, useLayout } from './layout'

beforeEach(() => {
  localStorage.clear()
  useLayout.getState().load('p1')
})

test('a case tab opens the panel only for content, on the first tab that has some', () => {
  const l = () => useLayout.getState()
  l().setEditorType('case')
  expect(l().panelVisible).toBe(false)
  l().setPanelContent('measurements', false)
  l().setPanelContent('problems', true)
  expect(l().panelVisible).toBe(true)
  expect(l().activePanelTab).toBe('problems')
  l().setPanelContent('problems', false)
  expect(l().panelVisible).toBe(false)
  // other editors keep their defaults whatever the content
  l().setPanelContent('measurements', true)
  l().setEditorType('queue')
  expect(l().panelVisible).toBe(true)
  l().setEditorType('run')
  expect(l().panelVisible).toBe(false)
  // back on a case tab the known content applies at once
  l().setEditorType('case')
  expect(l().panelVisible).toBe(true)
})

test("the user's choice for case tabs wins over the content and is remembered", () => {
  const l = () => useLayout.getState()
  l().setEditorType('case')
  l().setPanelContent('measurements', true)
  expect(l().panelVisible).toBe(true)
  l().set({ panelVisible: false })
  l().setPanelContent('problems', true)
  expect(l().panelVisible).toBe(false)
  l().load('p1')
  l().setEditorType('case')
  l().setPanelContent('measurements', true)
  expect(l().panelVisible).toBe(false)
})

test('default height: at most 220 px and about 20 % of the window; the old stored default is automatic', () => {
  expect(panelAutoHeight(800)).toBe(160)
  expect(panelAutoHeight(1440)).toBe(220)
  localStorage.setItem('rw.layout.p2', JSON.stringify({ panelHeight: 220 }))
  useLayout.getState().load('p2')
  expect(useLayout.getState().panelHeight).toBeNull()
  localStorage.setItem('rw.layout.p3', JSON.stringify({ panelHeight: 300 }))
  useLayout.getState().load('p3')
  expect(useLayout.getState().panelHeight).toBe(300)
})
