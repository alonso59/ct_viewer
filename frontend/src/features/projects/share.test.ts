// AUD-A1-11 (PRJ-03, PRJ-17): both links keep the current tab's deep link
import { deepLink } from './share'

test('deep links on the edit and the view-only base', () => {
  const loc = { pathname: '/p/01ABC/case/case_00001', search: '?item=x&layout=four-up' }
  expect(deepLink('http://h/p/01ABC', loc)).toBe('http://h/p/01ABC/case/case_00001?item=x&layout=four-up')
  expect(deepLink('http://h/v/tok/', loc)).toBe('http://h/v/tok/case/case_00001?item=x&layout=four-up')
  expect(deepLink('http://h/v/tok', { pathname: '/p/view-tok', search: '' })).toBe('http://h/v/tok')
})
