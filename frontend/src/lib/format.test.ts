// AUD-A2-13 (DCM-06): storage in the unit that fits, never "1 MB" for 3 KB.
import { fmtBytes } from './format'

test('bytes use the unit that fits', () => {
  expect(fmtBytes(3024)).toBe('3 KB')
  expect(fmtBytes(512)).toBe('512 B')
  expect(fmtBytes(2_400_000)).toBe('2.4 MB')
  expect(fmtBytes(1.25e9)).toBe('1.3 GB')
  expect(fmtBytes(null)).toBe('—')
})
