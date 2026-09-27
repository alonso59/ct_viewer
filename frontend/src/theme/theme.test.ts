// @vitest-environment jsdom
// UI-11 (AUD-A4-02): Dark by default; Light on request; System follows the OS preference
import { afterEach, expect, test, vi } from 'vitest'

import { useSettings } from '../state/settings'
import { applyTheme, resolveTheme } from './theme'

// jsdom has no matchMedia: stub it per test
const prefersLight = (light: boolean) =>
  vi.stubGlobal('matchMedia', (q: string) => ({ matches: light && q.includes('light'), media: q }) as MediaQueryList)

afterEach(() => vi.unstubAllGlobals())

test('dark applies until the user picks another, whatever the OS says', () => {
  expect(useSettings.getState().theme).toBe('dark')
  prefersLight(true)
  expect(resolveTheme('dark')).toBe('dark')
  expect(resolveTheme('light')).toBe('light')
})

test('system follows prefers-color-scheme', () => {
  prefersLight(true)
  expect(resolveTheme('system')).toBe('light')
  applyTheme('system')
  expect(document.documentElement.dataset.theme).toBe('light')
  prefersLight(false)
  expect(resolveTheme('system')).toBe('dark')
})
