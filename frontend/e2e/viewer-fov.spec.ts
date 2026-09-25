// VW-06/26 on the real backend: zoom acts on the view under the pointer only; Fit to window
// (header button or `F`) restores that view to 100 % and keeps its slice index.
import { resolve } from 'node:path'

import { expect, test, type Page } from '@playwright/test'

const FIX = resolve(import.meta.dirname, '../../.fixtures/synthetic')

const view = (page: Page, name: string) => page.getByRole('region', { name, exact: true })
const zoomText = (page: Page, name: string) => view(page, name).locator('.vp-corner-tr')

async function zoomIn(page: Page, name: string) {
  const box = (await view(page, name).locator('.vp-body').boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.keyboard.down('Control')
  await page.mouse.wheel(0, -300)
  await page.keyboard.up('Control')
}

test('zoom one view, the others unchanged; Fit restores it and keeps the slice index', async ({ page }) => {
  await page.goto(`/open?path=${encodeURIComponent(`${FIX}/Dataset900/nifti/04_case_00002_0000.nii.gz`)}`)
  await expect(page.locator('.vp').first()).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })

  // Move off the centre slice so "kept" is meaningful
  const axialBody = view(page, 'Axial').locator('.vp-body')
  const box = (await axialBody.boundingBox())!
  const index = view(page, 'Axial').locator('.vp-index')
  const centre = await index.textContent()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, 100)
  await expect(index).not.toHaveText(centre!)
  const before = await index.textContent()

  await zoomIn(page, 'Axial')
  await expect(zoomText(page, 'Axial')).toHaveText(/\d+ %/)
  await expect(zoomText(page, 'Sagittal')).toHaveCount(0)
  await expect(zoomText(page, 'Coronal')).toHaveCount(0)

  await view(page, 'Axial').getByRole('button', { name: 'Fit to window' }).click()
  await expect(zoomText(page, 'Axial')).toHaveCount(0) // 100 %: no corner text
  await expect(index).toHaveText(before!)

  // `F` fits the view under the pointer only
  await zoomIn(page, 'Sagittal')
  await zoomIn(page, 'Coronal')
  await expect(zoomText(page, 'Coronal')).toHaveText(/\d+ %/)
  await page.keyboard.press('f')
  await expect(zoomText(page, 'Coronal')).toHaveCount(0)
  await expect(zoomText(page, 'Sagittal')).toHaveText(/\d+ %/)
})

/** Crosshair position in tile px: the lines move with the image */
async function cross(page: Page, name: string): Promise<[number, number]> {
  const px = (sel: string, prop: 'left' | 'top') => view(page, name).locator(sel).evaluate((e, p) => parseFloat((e as unknown as { style: Record<string, string> }).style[p] ?? ''), prop)
  return [await px('.vp-cross-v', 'left'), await px('.vp-cross-h', 'top')]
}

test('pan: the image follows the pointer in every view and both conventions (VW-06, VW-25)', async ({ page }) => {
  await page.goto(`/open?path=${encodeURIComponent(`${FIX}/Dataset900/nifti/04_case_00002_0000.nii.gz`)}`)
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })
  await expect(page.locator('.vp-cross-v').first()).toBeAttached()
  for (const convention of ['radiological', 'neurological'] as const) {
    // The convention is a display setting (VW-25); Open mode has no project to set it from
    await page.evaluate(async (c) => {
      const store = '/src/state/index.ts'
      const { useViewerSync } = await import(/* @vite-ignore */ store)
      useViewerSync.setState((s: { display: object }) => ({ display: { ...s.display, convention: c } }))
    }, convention)
    // Let the flipped image redraw and the crosshair lines follow before reading the baseline
    await page.waitForFunction('new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(() => r(true)))))')
    for (const name of ['Axial', 'Sagittal', 'Coronal']) {
      const box = (await view(page, name).locator('.vp-body').boundingBox())!
      const [x0, y0] = await cross(page, name)
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
      await page.mouse.down({ button: 'middle' })
      await page.mouse.move(box.x + box.width / 2 + 40, box.y + box.height / 2 + 30, { steps: 5 })
      await page.mouse.up({ button: 'middle' })
      const moved = async () => {
        const [x, y] = await cross(page, name)
        return [Math.round(x - x0), Math.round(y - y0)]
      }
      await expect.poll(moved, { message: `${convention} ${name}` }).toEqual([40, 30])
    }
  }
})
