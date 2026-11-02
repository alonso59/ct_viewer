// TST-25 (FE-08, UI-01, UI-11): axe scans the key screens, and a keyboard walk checks the skip
// link, the F6 regions and a visible focus ring. A serious or critical violation fails unless its
// rule is in ALLOWED with the reason; the list may only shrink: an entry that no screen needs any
// more fails the last test, so it gets removed.
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

import { FIXTURES, importedProject } from './helpers'
import { gotoOpen } from './openMode'

/** Rule id → why it is still accepted. Only ever remove entries. */
const ALLOWED: Record<string, string> = {}

const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice']
const seen = new Set<string>()

test.describe.configure({ mode: 'serial' })

async function scan(page: Page, screen: string) {
  const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze()
  for (const v of violations) seen.add(v.id)
  const blocking = violations.filter((v) => (v.impact === 'serious' || v.impact === 'critical') && !(v.id in ALLOWED))
  expect(blocking.map((v) => `${screen}: ${v.id} (${v.impact}) ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([])
}

// e2e has no DOM lib: page scripts are strings
const FOCUSED_TAG = 'document.activeElement?.tagName.toLowerCase() ?? ""'
const FOCUS_RING = `(() => {
  const el = document.activeElement
  if (!el || el === document.body) return 'ring'
  const s = getComputedStyle(el)
  return (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2) || s.boxShadow !== 'none' ? 'ring' : 'no ring: ' + el.tagName + '.' + el.className
})()`

test('home, converter and Open mode have no serious violations', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Radiology Workbench' })).toBeVisible()
  await scan(page, 'home')
  await page.getByRole('button', { name: /Convert DICOM/ }).click()
  const converter = page.getByRole('dialog', { name: 'Convert DICOM' })
  await expect(converter).toBeVisible()
  await scan(page, 'converter')
  await page.keyboard.press('Escape')
  await expect(converter).toBeHidden()
  await gotoOpen(page, `${FIXTURES}/dicom/P900`)
  await expect(page.locator('.vp').first()).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })
  await scan(page, 'open mode')
})

test('the workbench, a case tab, the Jobs panel, the palette, shortcuts and settings have no serious violations', async ({ page }) => {
  test.setTimeout(180_000)
  const pid = await importedProject(`a11y ${Date.now()}`)
  await page.goto(`/p/${pid}`)
  await expect(page.getByRole('tree', { name: 'Project' })).toBeVisible({ timeout: 30_000 })
  await scan(page, 'workbench')
  await page.goto(`/p/${pid}/case/case_00001`)
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })
  await scan(page, 'case tab')
  const jobs = page.getByRole('tab', { name: /^Jobs/ })
  if (!(await jobs.isVisible())) await page.keyboard.press('ControlOrMeta+j')
  await jobs.click()
  await scan(page, 'jobs panel')
  await page.keyboard.press('ControlOrMeta+Shift+p')
  const palette = page.getByRole('dialog')
  await expect(palette.getByRole('combobox')).toBeVisible()
  await scan(page, 'command palette')
  await palette.getByRole('combobox').fill('Keyboard shortcuts')
  await palette.getByRole('option', { name: /Keyboard shortcuts/ }).click()
  const keys = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
  await expect(keys.getByRole('region', { name: 'Shortcuts' })).toBeVisible()
  await scan(page, 'keyboard shortcuts')
  await page.keyboard.press('Escape')
  await expect(keys).toBeHidden()
  await page.keyboard.press('ControlOrMeta+,')
  await expect(page.getByRole('complementary', { name: 'Settings' })).toBeVisible()
  await scan(page, 'settings')
})

test('the skip link reaches the editor, F6 walks the regions and focus is always visible (UI-01, FE-08)', async ({ page }) => {
  test.setTimeout(120_000)
  const pid = await importedProject(`a11y keys ${Date.now()}`)
  await page.goto(`/p/${pid}`)
  await expect(page.getByRole('tree', { name: 'Project' })).toBeVisible({ timeout: 30_000 })
  // the first Tab stop is the skip link; Enter moves focus into the editor area
  await page.keyboard.press('Tab')
  const skip = page.getByRole('link', { name: 'Skip to editor' })
  await expect(skip).toBeFocused()
  await expect(skip).toBeInViewport()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('main', { name: 'Editor area' })).toBeFocused()
  // F6 visits the regions; each one is a landmark
  const visited = new Set<string>()
  for (let i = 0; i < 5; i++) {
    await page.keyboard.press('F6')
    visited.add(await page.evaluate<string>(FOCUSED_TAG))
  }
  expect([...visited]).toEqual(expect.arrayContaining(['header', 'aside', 'main']))
  expect([...visited].filter((tag) => !['header', 'aside', 'main', 'section'].includes(tag))).toEqual([])
  // every Tab stop on the home shows a focus ring
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Radiology Workbench' })).toBeVisible()
  const missing: string[] = []
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press('Tab')
    const ring = await page.evaluate<string>(FOCUS_RING)
    if (ring !== 'ring') missing.push(ring)
  }
  expect(missing).toEqual([])
})

test('the allow-list names only rules that still occur', () => {
  expect(Object.keys(ALLOWED).filter((id) => !seen.has(id))).toEqual([])
})
