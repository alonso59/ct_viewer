// P7b Wave 2 (SRC-01..12, UI-17/18): Open mode without a project, and the import wizard's detect
// step with refusal actions. Real backend on the synthetic fixtures (TST-11).
// AUD-A1-19 (NFR-17, API-07): the URL carries the session id, never the path; reload keeps the
// session, an ended session shows its next actions (UI-18).
import { expect, test } from '@playwright/test'

import { openViaHistoryState } from './openMode'

test('open a NIfTI file from the workspace home without a project', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto('/')
  await page.getByRole('button', { name: /Open file or folder/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Open file or folder' })
  const folders = dialog.getByRole('listbox', { name: 'Folders' })
  await folders.getByRole('button', { name: /synthetic/ }).click()
  await folders.getByRole('button', { name: /Dataset900/ }).click()
  await folders.getByRole('button', { name: /^nifti$/ }).click()
  await folders.getByRole('button', { name: '01_case_00001_0000.nii.gz' }).click()
  await dialog.getByRole('button', { name: 'Open file' }).click()

  await expect(page).toHaveURL(/\/open\/[0-9A-Z]{26}$/)
  expect(page.url()).not.toMatch(/nii|Dataset900|path=/)
  await expect(page.getByText('No project: nothing is saved')).toBeVisible()
  const files = page.getByRole('listbox', { name: 'Files' })
  await expect(files.getByRole('button', { name: /01_case_00001_0000/ })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('button', { name: 'Create project from this' })).toBeEnabled()
  // the path is shown on the page (server state), not carried by the URL
  await expect(page.locator('.open-path')).toContainText('01_case_00001_0000.nii.gz')

  // reload restores the session from the server
  await page.reload()
  await expect(files.getByRole('button', { name: /01_case_00001_0000/ })).toHaveAttribute('aria-selected', 'true')

  // Close ends it; going back shows the ended session with its next actions (UI-18)
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.goBack()
  const alert = page.getByRole('alert')
  await expect(alert).toContainText('This Open session has ended')
  await expect(alert.getByRole('button', { name: 'Choose another file or folder' })).toBeVisible()
  await alert.getByRole('button', { name: 'Go to the workspace home' }).click()
  await expect(page).toHaveURL(/\/$/)
  expect(errors).toEqual([])
})

test('open mode refuses a folder with nothing to open, with next actions', async ({ page }) => {
  await page.goto('/')
  await openViaHistoryState(page, '/nope/not-allowed')
  const alert = page.getByRole('alert')
  await expect(alert).toContainText('path-outside-root')
  await expect(page).toHaveURL(/\/open$/) // a refused path never reaches the URL either
})

test('a bare /open offers the next steps instead of an empty page', async ({ page }) => {
  await page.goto('/open')
  const alert = page.getByRole('alert')
  await expect(alert).toContainText('No Open session')
  await alert.getByRole('button', { name: 'Choose another file or folder' }).click()
  await expect(page.getByRole('dialog', { name: 'Open file or folder' })).toBeVisible()
})
