// SRC-20, PRJ-07/15, VW-19: real mask import/removal/reimport and label catalog editing.
import { expect, test, type Locator } from '@playwright/test'

import { api, importedProject } from './helpers'

async function chooseMasks(dialog: Locator) {
  const folders = dialog.getByRole('listbox', { name: 'Folders' })
  await folders.getByRole('button', { name: /synthetic/ }).click()
  await folders.getByRole('button', { name: /^Dataset900(?:\s|$)/ }).click()
  await dialog.getByLabel('Path template below the selected folder').fill('seg/{scan_idx}_{case_id}.nii.gz')
}

test('mask sets restore after reindex and reimport without editing source data; catalogs save separately', async ({ page, browserName }) => {
  test.setTimeout(150_000)
  const pid = await importedProject(`Segmentation lifecycle ${browserName} ${Date.now()}`)
  const sets = () => api<{ seg_id: string; artifact_id: string | null }[]>('GET', `/projects/${pid}/segmentations`)
  const waitJob = async (id: string) => {
    await expect.poll(async () => (await api<{ status: string }>('GET', `/jobs/${id}`)).status, { timeout: 30_000 }).toBe('succeeded')
  }
  await page.goto(`/p/${pid}/case/case_00001`)
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })
  const inspector = page.locator('.inspector')
  if (!(await inspector.isVisible())) {
    await page.getByRole('banner').getByRole('button', { name: /^Layout/ }).click()
    await page.getByRole('menuitemcheckbox', { name: /Inspector/ }).click()
  }
  const all = inspector.getByRole('checkbox', { name: 'Toggle all segmentation labels' })
  await all.check()
  await expect(all).toBeChecked()
  await all.uncheck()
  await expect(all).not.toBeChecked()
  await all.check()

  await inspector.getByRole('button', { name: 'Import segmentation…' }).click()
  let dialog = page.getByRole('dialog', { name: 'Import segmentation set' })
  await chooseMasks(dialog)
  await dialog.getByLabel('Set ID').fill('reviewed')
  const imported = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/segmentations/imports'))
  await dialog.getByRole('button', { name: 'Import segmentation…' }).click()
  const response = await imported
  expect(response.status()).toBe(202)
  const first = await response.json() as { import_id: string; job_id: string }
  await waitJob(first.job_id)
  await expect(inspector.getByLabel('Segmentation set').locator('option[value="reviewed"]')).toHaveCount(1)
  await inspector.getByLabel('Segmentation set').selectOption('reviewed')
  await inspector.getByRole('button', { name: 'Remove', exact: true }).click()
  await page.getByRole('dialog', { name: 'Remove segmentation set' }).getByRole('button', { name: 'Remove', exact: true }).click()
  await expect.poll(async () => (await sets()).some((set) => set.seg_id === 'reviewed')).toBe(false)

  const reindex = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/segmentations/reindex'))
  await inspector.getByRole('button', { name: 'Reindex', exact: true }).click()
  await waitJob(((await (await reindex).json()) as { job_id: string }).job_id)
  await inspector.getByRole('button', { name: 'Restore', exact: true }).click()
  await expect.poll(async () => (await sets()).some((set) => set.seg_id === 'reviewed')).toBe(true)
  const restored = await page.request.get(`/api/v1/projects/${pid}/items/case_00001.01.complete.-/mask?seg=reviewed`)
  expect(restored.status()).toBe(200)

  await inspector.getByLabel('Segmentation set').selectOption('reviewed')
  await inspector.getByRole('button', { name: 'Remove', exact: true }).click()
  await page.getByRole('dialog', { name: 'Remove segmentation set' }).getByRole('button', { name: 'Remove', exact: true }).click()
  await inspector.getByRole('button', { name: 'Reimport', exact: true }).click()
  dialog = page.getByRole('dialog', { name: 'Import segmentation set' })
  await expect(dialog.getByLabel('Set ID')).toHaveValue('reviewed')
  await chooseMasks(dialog)
  const reimported = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/segmentations/imports'))
  await dialog.getByRole('button', { name: 'Import segmentation…' }).click()
  const next = await (await reimported).json() as { import_id: string; job_id: string }
  await waitJob(next.job_id)
  expect(next.import_id).not.toBe(first.import_id)
  expect((await sets()).filter((set) => set.seg_id === 'reviewed')).toHaveLength(1)

  await page.goto(`/p/${pid}/settings`)
  await page.getByRole('tab', { name: 'Labels', exact: true }).click()
  const removeLabel = page.getByRole('button', { name: 'Remove label kidney from the catalog' })
  await removeLabel.click()
  await page.getByRole('button', { name: 'Discard my changes' }).click()
  await expect(removeLabel).toBeVisible()
  await page.getByRole('combobox', { name: 'Label import mode' }).selectOption('replace')
  const catalog = [{ value: 1, name: 'Reviewed kidney', color: '#12ABEF', opacity: 0.4, visible: true }]
  await page.getByLabel('Import label file…').setInputFiles({ name: 'catalog.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ label_map: catalog })) })
  await expect(page.locator('.psettings-table').getByRole('textbox').first()).toHaveValue('Reviewed kidney')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(async () => (await api<{ label_map: unknown[] }>('GET', `/projects/${pid}`)).label_map).toEqual(catalog)
  await page.reload()
  await page.getByRole('tab', { name: 'Labels', exact: true }).click()
  await expect(page.locator('.psettings-table').getByRole('textbox').first()).toHaveValue('Reviewed kidney')
})
