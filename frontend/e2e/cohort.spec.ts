// TST (COH-01..07): open Cohort, pick a group, filter from a cell, read the column summary, compare a
// case's scans and open one in the viewer.
import { expect, test } from '@playwright/test'

import { api, importedProject } from './helpers'

test('cohort journey: group, filter, summary, compare, open in viewer', async ({ page }) => {
  test.setTimeout(120_000)
  const pid = await importedProject(`Cohort ${Date.now()}`)
  await page.goto(`/p/${pid}/cohort`)
  await page.getByRole('navigation', { name: 'Activity bar' }).getByRole('button', { name: 'Cohort' }).click()
  await page.getByRole('button', { name: /^Equipment/ }).click()
  const firstCell = page.locator('.cohort-row-case .cohort-cell').first()
  await expect(firstCell).toBeVisible({ timeout: 30_000 })
  const cases = page.locator('.cohort-row-case')
  const before = await cases.count()

  // Summary of the column, then a filter from the cell menu
  await firstCell.click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Summarize this column' }).click()
  await expect(page.getByRole('region', { name: /^Distribution of / })).toBeVisible()
  await firstCell.click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Filter by this value' }).click()
  await expect(page.locator('.item-filter-chip').first()).toBeVisible()
  expect(await cases.count()).toBeLessThanOrEqual(before)

  // Compare the scans of the first case
  await firstCell.click({ button: 'right' })
  await page.getByRole('menuitem', { name: "Compare this case's scans" }).click()
  const compare = page.getByRole('region', { name: 'Compared fields' })
  await expect(compare.getByRole('columnheader').nth(1)).toBeVisible()
  await page.getByRole('checkbox', { name: 'Differences only' }).check()

  // Open the case's scan in the viewer
  await firstCell.click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Open in viewer' }).click()
  await expect(page).toHaveURL(/\/case\//)
})

test('cohort clinical editing, balance check and timeline events', async ({ page }) => {
  test.setTimeout(120_000)
  const pid = await importedProject(`Cohort K2 ${Date.now()}`)
  const base = `/plugins/labeling/projects/${pid}/tables`
  const reviewer = { 'X-Reviewer': 'Dr. E2E' }
  await api('POST', base, { name: 'Review', level: 'case', columns: [{ name: 'Grade', type: 'category', levels: ['G1', 'G2'] }] }, reviewer)
  await api('POST', base, { name: 'Events', level: 'event', columns: [] }, reviewer)
  await page.addInitScript(() => localStorage.setItem('rw.reviewer', JSON.stringify({ state: { name: 'Dr. E2E' }, version: 0 })))
  // The catalog rebuild after a table write is deferred, and a page that loads before it misses
  // the `project.updated` event sent before its stream opens; wait for the rebuilt catalog.
  await expect
    .poll(async () => (await api<{ variables: { origin: string }[] }>('GET', `/projects/${pid}/variables`)).variables.some((v) => v.origin === 'clinical'), { timeout: 30_000 })
    .toBe(true)
  await page.goto(`/p/${pid}/cohort`)
  await page.getByRole('navigation', { name: 'Activity bar' }).getByRole('button', { name: 'Cohort' }).click()
  await page.getByRole('button', { name: /^Clinical & labels/ }).click()
  const cell = page.locator('.cohort-row-case .cohort-cell').first()
  await expect(cell).toBeVisible({ timeout: 30_000 })

  // Edit a clinical cell in place; the value shows in the grid
  await cell.locator('.cohort-editable').dblclick()
  await page.getByRole('combobox', { name: 'Grade' }).selectOption('G2')
  await expect(cell).toContainText('G2', { timeout: 15_000 })

  // Balance check opens with two pickers
  await page.getByRole('button', { name: 'Balance check' }).click()
  await expect(page.getByRole('region', { name: 'Balance check' })).toBeVisible()
  await page.getByRole('button', { name: 'Close Balance check' }).click()

  // Timeline: add an event to the first case
  await cell.click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Timeline of this case' }).click()
  const timeline = page.getByRole('region', { name: /^Timeline of / })
  await expect(timeline).toBeVisible()
  await timeline.getByRole('combobox', { name: 'Kind' }).selectOption('Death')
  await timeline.getByRole('textbox', { name: /^Day/ }).fill('120')
  await timeline.getByRole('button', { name: 'Add event' }).click()
  await expect(timeline.getByText('Death, day 120 (Events)')).toBeVisible({ timeout: 15_000 })
})
