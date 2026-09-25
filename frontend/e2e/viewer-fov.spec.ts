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
