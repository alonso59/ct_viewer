// SRC-18/10/14, D09/U08: complete series and later files remain reachable without
// replacing the active volume when paging. Real services, WebGL and read-only inputs.
import { chmodSync, copyFileSync, cpSync, linkSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'

import { expect, test } from '@playwright/test'

import { DATASET, FIXTURES } from './helpers'
import { openViaHistoryState } from './openMode'
import { fixtureHashes } from './tst07'

function permissions(root: string, writable: boolean) {
  chmodSync(root, writable ? 0o700 : 0o500)
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name)
    if (entry.isDirectory()) permissions(path, writable)
    else chmodSync(path, writable ? 0o600 : 0o400)
  }
}

test('open later files, attach and save while keeping pages bounded and sources unchanged', async ({ page }) => {
  const root = mkdtempSync(join(process.env.E2E_DATASETS!, 'open-paging-'))
  const images = join(root, 'images')
  const masks = join(root, 'masks')
  mkdirSync(images)
  mkdirSync(masks)
  copyFileSync(join(DATASET, 'nifti/01_case_00001_0000.nii.gz'), join(images, '0000.nii.gz'))
  for (let n = 1; n < 503; n++) linkSync(join(images, '0000.nii.gz'), join(images, `${String(n).padStart(4, '0')}.nii.gz`))
  copyFileSync(join(DATASET, 'seg/01_case_00001.nii.gz'), join(masks, 'seg.nii.gz'))
  cpSync(join(FIXTURES, 'dicom/P900'), join(images, 'dicom'), { recursive: true })
  const before = fixtureHashes(root)
  permissions(root, false)
  try {
    await page.goto('/')
    await openViaHistoryState(page, images)
    await expect(page).toHaveURL(/\/open\/[0-9A-Z]{26}$/, { timeout: 30_000 })
    const files = page.getByRole('listbox', { name: 'Files' })
    await expect(files.getByRole('button')).toHaveCount(50)
    await expect(page.getByRole('button', { name: 'Convert DICOM…' })).toBeVisible()
    await expect(page.locator('.vp').first()).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })
    await expect(page.getByTestId('conv-chip')).toHaveCount(0)
    for (let n = 1; n <= 10; n++) {
      await page.getByRole('button', { name: 'Next page', exact: true }).click()
      await expect(files.getByRole('button').first()).toContainText(`${String(n * 50).padStart(4, '0')}.nii.gz`)
    }
    await files.getByRole('button', { name: '0502.nii.gz' }).click()
    await expect(files.getByRole('button', { name: '0502.nii.gz' })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('button', { name: 'Attach segmentation…' })).toBeEnabled()
    await page.getByRole('button', { name: 'Attach segmentation…' }).click()
    const attach = page.getByRole('dialog', { name: 'Attach a segmentation' })
    await attach.getByRole('button', { name: 'seg.nii.gz', exact: true }).click()
    await attach.getByRole('button', { name: 'Attach', exact: true }).click()
    await expect(attach).not.toBeVisible()
    await expect(files.getByRole('button', { name: '0502.nii.gz' }).locator('.codicon-layers')).toHaveCount(1)
    await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })
    await page.getByRole('button', { name: 'Previous page', exact: true }).click()
    await expect(files.getByRole('button').first()).toContainText('0450.nii.gz')
    await page.getByRole('button', { name: 'Save as NIfTI…' }).click()
    const save = page.getByRole('dialog', { name: 'Save 0502.nii.gz as NIfTI' })
    const response = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/items/502/save'))
    await save.getByRole('button', { name: 'Save', exact: true }).click()
    const saved = await response
    expect(saved.status()).toBe(201)
    const result = await saved.json() as { path: string }
    expect(readFileSync(result.path)).toEqual(readFileSync(join(images, '0502.nii.gz')))
    await expect(save).not.toBeVisible()
    expect(fixtureHashes(root)).toEqual(before)
  } finally {
    permissions(root, true)
    rmSync(root, { recursive: true, force: true })
  }
})
