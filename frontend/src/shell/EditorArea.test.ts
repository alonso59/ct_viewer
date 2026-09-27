// AUD-A1-02 (FE-04): a new case, item or tab is a history entry; a layout tweak is not
import { isNewEntry, loadTabs, saveTabs } from './EditorArea'

test('history entries', () => {
  expect(isNewEntry('/p/P/case/c1?layout=four-up', '/p/P/case/c2?layout=four-up')).toBe(true)
  expect(isNewEntry('/p/P/case/c1?item=a&layout=four-up', '/p/P/case/c1?item=b&layout=four-up')).toBe(true)
  expect(isNewEntry('/p/P/case/c1?layout=four-up', '/p/P/queue')).toBe(true)
  expect(isNewEntry('/p/P/case/c1?item=a&layout=four-up', '/p/P/case/c1?item=a&layout=one-up-axial')).toBe(false)
})

// FE-04 (AUD-A4-02): open editor tabs persist per project in localStorage
test('tabs persist per project', () => {
  localStorage.clear()
  expect(loadTabs('P1')).toBeNull()
  saveTabs('P1', { panels: { a: 1 } })
  saveTabs('P2', { panels: { b: 2 } })
  expect(loadTabs('P1')).toEqual({ panels: { a: 1 } })
  expect(loadTabs('P2')).toEqual({ panels: { b: 2 } })
  localStorage.setItem('rw.tabs.P3', '{not json')
  expect(loadTabs('P3')).toBeNull()
})
