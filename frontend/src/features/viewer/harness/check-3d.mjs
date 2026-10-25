// 3D view WebGL regression. Start the fixture harness on :5175 (make fixtures first).
// Run: node src/features/viewer/harness/check-3d.mjs
// HARNESS_URL, CHROME and CDP_URL optionally select the server/browser.
import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'

const browser = process.env.CDP_URL
  ? await chromium.connectOverCDP(process.env.CDP_URL)
  : await chromium.launch({ executablePath: process.env.CHROME || undefined })
const context = await browser.newContext({ viewport: { width: 1500, height: 1000 }, deviceScaleFactor: 1 })
const page = await context.newPage()
const errors = []
page.on('pageerror', (error) => errors.push(error.message))
const settle = () => page.waitForTimeout(800) // Include the deferred 3D proxy refresh.
const slices = async () => Promise.all(['axial', 'sagittal', 'coronal'].map((id) => page.locator(`[data-tile="${id}"]`).screenshot()))
try {
  await page.goto(`${process.env.HARNESS_URL || 'http://127.0.0.1:5175'}/src/features/viewer/harness/index.html?case=case_00001&item=case_00001.01.complete.-`)
  await page.waitForFunction(() => performance.getEntriesByName('rw:mask').length > 0, null, { timeout: 60_000 })
  await settle()
  const before = await slices()
  await page.getByRole('button', { name: 'Mask only', exact: true }).click()
  await settle()
  assert.deepEqual(await slices(), before, 'Mask only must preserve all three visible 2D slices')
  await page.evaluate(() => window.__viewer.setWindow(400, 50))
  await settle()
  assert.deepEqual(await slices(), before, 'A deferred proxy redraw must preserve the 2D slices')
  await page.getByLabel('3D view options', { exact: true }).first().click()
  const panel = page.getByRole('dialog', { name: '3D view options' })
  assert.equal(await panel.evaluate((el) => el.parentElement === document.body), true, 'Settings must escape viewer clipping')
  const start = await panel.boundingBox()
  const title = await panel.locator('.vp-3d-panel-header').boundingBox()
  await page.mouse.move(title.x + 60, title.y + 15)
  await page.mouse.down()
  await page.mouse.move(title.x - 100, title.y + 45, { steps: 8 })
  await page.mouse.up()
  const moved = await panel.boundingBox()
  assert.ok(moved.x < start.x - 100, 'Settings must follow dragging')
  await page.keyboard.press('Escape')
  assert.equal(await panel.count(), 0)
  await page.getByRole('button', { name: '3D view options', exact: true }).click()
  assert.equal((await panel.boundingBox()).x, moved.x, 'Settings must retain their position when reopened')
  await page.getByRole('button', { name: 'Detailed', exact: true }).click()
  for (const plane of ['Axial', 'Sagittal', 'Coronal']) await page.getByRole('combobox', { name: plane, exact: true }).selectOption('slice')
  await page.keyboard.press('Escape')
  await settle()
  assert.deepEqual(await slices(), before, '3D slice planes must preserve the 2D slices')
  const sceneBefore = await page.locator('[data-tile="3d"]').screenshot()
  await page.locator('.vp-slider').first().fill('12')
  await settle()
  assert.notDeepEqual(await page.locator('[data-tile="3d"]').screenshot(), sceneBefore, 'The 3D plane must follow the slice slider')
  await page.getByRole('button', { name: 'Mask only', exact: true }).click()
  await settle()
  assert.equal(await page.evaluate(() => window.__viewer.render3d.volume), true)
  assert.equal(await page.evaluate(() => window.__viewer.nv.gl.getError()), 0)
  assert.deepEqual(errors, [])
  console.log('PASS: mask only, deferred redraw, 3D image planes, slider tracking, CT restore; no WebGL errors')
} finally {
  await context.close()
  await browser.close()
}
