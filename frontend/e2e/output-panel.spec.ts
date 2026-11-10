// UI-29 / FE-09: every Log channel uses the one log view. Activity lists this session's events
// while a job runs, the workbench stays mounted, and the text filter, the copy count and a Download
// made in the browser act on the lines shown.
import { readFileSync } from 'node:fs'

import { expect, test } from '@playwright/test'

import { importedProject } from './helpers'

test('Activity follows a job, filters by text, copies with a count and downloads a .log', async ({ page }) => {
  test.setTimeout(120_000)
  const pid = await importedProject(`Output ${Date.now()}`)
  await page.goto(`/p/${pid}`)
  await expect(page.getByRole('tree', { name: 'Explorer' })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: /Compute full hashes/ }).click()
  const output = page.getByRole('tab', { name: 'Log', exact: true })
  const log = page.getByRole('log')
  // a starting job can move the bottom panel while it is being opened: retry until the log shows
  await expect(async () => {
    if (!(await output.isVisible())) await page.keyboard.press('ControlOrMeta+j')
    await output.click({ timeout: 2_000 })
    await expect(log).toBeVisible({ timeout: 2_000 })
  }).toPass({ timeout: 30_000 })
  await expect(log).toContainText(/\[job\] Full hash: Completed/, { timeout: 90_000 })
  await expect(page.getByRole('tree', { name: 'Explorer' })).toBeVisible()

  const search = page.getByRole('searchbox', { name: 'Filter lines' })
  await search.fill('Full hash')
  await expect(log).toContainText('Full hash')
  // Copy names its count; a browser that blocks the clipboard says so instead
  await page.getByRole('button', { name: 'Copy', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: /Copied \d+ (of \d+ )?lines?|blocked the clipboard/ })).toBeVisible()
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download', exact: true }).click()])
  expect(download.suggestedFilename()).toBe('activity.log')
  expect(readFileSync(await download.path(), 'utf8')).toContain('[job] Full hash: Completed')

  await search.fill('no line has these words')
  await expect(log).toContainText('No line matches the filter')
})
