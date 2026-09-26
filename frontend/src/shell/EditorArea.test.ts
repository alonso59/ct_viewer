// AUD-A1-02 (FE-04): a new case, item or tab is a history entry; a layout tweak is not
import { isNewEntry } from './EditorArea'

test('history entries', () => {
  expect(isNewEntry('/p/P/case/c1?layout=four-up', '/p/P/case/c2?layout=four-up')).toBe(true)
  expect(isNewEntry('/p/P/case/c1?item=a&layout=four-up', '/p/P/case/c1?item=b&layout=four-up')).toBe(true)
  expect(isNewEntry('/p/P/case/c1?layout=four-up', '/p/P/queue')).toBe(true)
  expect(isNewEntry('/p/P/case/c1?item=a&layout=four-up', '/p/P/case/c1?item=a&layout=one-up-axial')).toBe(false)
})
