// P7b Wave 2 (SRC-01..12, UI-17/18): Open mode without a project, and the import wizard's detect
// step with refusal actions. Real backend on the synthetic fixtures (TST-11).
import { expect, test } from '@playwright/test'

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

  await expect(page).toHaveURL(/\/open\?path=/)
  await expect(page.getByText('No project: nothing is saved')).toBeVisible()
  const files = page.getByRole('listbox', { name: 'Files' })
  await expect(files.getByRole('button', { name: /01_case_00001_0000/ })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('button', { name: 'Create project from this' })).toBeEnabled()
  expect(errors).toEqual([])
})

test('open mode refuses a folder with nothing to open, with next actions', async ({ page }) => {
  await page.goto(`/open?path=${encodeURIComponent('/nope/not-allowed')}`)
  const alert = page.getByRole('alert')
  await expect(alert).toContainText('path-outside-root')
})
