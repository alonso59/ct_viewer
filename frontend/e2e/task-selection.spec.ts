// TSK-03 / API-68: a real project uses indexed identities, exact file selection and server paging.
import { expect, test } from '@playwright/test'

import { api, importedProject } from './helpers'

test('select all covers every page and page size changes preserve a fixed scrolling table', async ({ page }, testInfo) => {
  const pid = await importedProject(`All selection ${Date.now()}`)
  const { total } = await api<{ total: number }>('GET', `/projects/${pid}/items?limit=1`)
  expect(total).toBeGreaterThan(50)
  await page.goto(`/p/${pid}/tasks/segment.threshold`)
  await page.getByRole('radio', { name: 'Item list' }).click()
  const all = page.getByRole('checkbox', { name: 'Select all matching files' })
  await all.check()
  await expect(page.getByText(`${total} selected`, { exact: true })).toBeVisible({ timeout: 30_000 })
  const before = (await page.locator('.task-picker-grid').boundingBox())!.height
  await page.getByRole('combobox', { name: 'Rows per page' }).selectOption('500')
  await expect(page.getByText(`${total} of ${total} matching files on this page`, { exact: true })).toBeVisible({ timeout: 15_000 })
  const after = (await page.locator('.task-picker-grid').boundingBox())!.height
  expect(after).toBe(before)
  await page.screenshot({ path: `../build/verification/task-picker-${testInfo.project.name}.png` })
  await all.uncheck()
  await expect(page.getByText('0 selected', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Run', exact: true })).toBeDisabled()
})

test('filter files, keep selection across filters and submit only the checked items', async ({ page }) => {
  const pid = await importedProject(`Selection ${Date.now()}`)
  await api('PUT', `/projects/${pid}/roots/DERIVED`, { path: process.env.E2E_DERIVED, role: 'derived' })
  await page.goto(`/p/${pid}/tasks/segment.threshold`)
  await page.getByRole('radio', { name: 'Item list' }).click()
  const search = page.getByRole('searchbox', { name: 'Search files or cases' })
  const picker = page.getByRole('table', { name: 'Files for this task' })
  for (const n of ['01', '02']) {
    const file = `01_case_000${n}_0000.nii.gz`
    await search.fill(file)
    await expect(picker.getByRole('checkbox', { name: `Select file ${file}`, exact: true })).toBeVisible()
    await picker.getByRole('checkbox', { name: 'Select files on this page', exact: true }).check()
  }
  await expect(page.getByText('2 selected', { exact: true })).toBeVisible()
  await expect(page.getByText('2 of 2 ready', { exact: true })).toBeVisible()
  await page.getByRole('checkbox', { name: 'Group by case' }).uncheck()
  await expect(picker.getByRole('button', { name: /case_00002/ })).toHaveCount(0)
  await expect(picker.getByText('case_00002', { exact: true })).toBeVisible()
  const request = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith(`/projects/${pid}/task-runs`))
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  expect((await request).postDataJSON().selection.item_ids).toEqual(['case_00001.01.complete.-', 'case_00002.01.complete.-'])
  const row = page.locator('.task-run').first()
  await row.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(row.getByText('Cancelled', { exact: true })).toBeVisible({ timeout: 15_000 })
})
