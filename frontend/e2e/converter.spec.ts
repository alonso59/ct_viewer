// UI-25 / TSK-13 / ADR-0020: convert a DICOM folder without a project from the converter overlay,
// then create a neutral project from the dataset; the phase arrives as a layer. Real backend.
import { expect, test } from '@playwright/test'

import { API } from './helpers'

test('convert without a project, then create a project from the dataset', async ({ page, browserName }) => {
  test.setTimeout(120_000)
  const name = `conv-${browserName}-${Date.now()}`
  await page.goto('/')
  await page.getByRole('button', { name: /Convert DICOM/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Convert DICOM' })
  const folders = dialog.getByRole('listbox', { name: 'Folders' })
  await folders.getByRole('button', { name: /synthetic/ }).click()
  await folders.getByRole('button', { name: /^dicom$/ }).click()
  await dialog.getByRole('button', { name: 'Next' }).click()
  await dialog.getByLabel('Dataset name').fill(name)
  await expect(dialog.getByRole('checkbox', { name: /phase analyzer/ })).toBeChecked()
  await dialog.getByRole('button', { name: 'Dry run' }).click()
  await dialog.getByRole('button', { name: /Convert \d+ series/ }).click()
  await dialog.getByRole('button', { name: 'Show the result' }).click({ timeout: 60_000 })
  await expect(dialog.getByText(`Dataset ${name} is ready.`)).toBeVisible()
  const runs = (await (await fetch(`${API}/task-runs`)).json()) as { name: string; dataset_dir: string; status: string }[]
  const run = runs.find((r) => r.name === name)
  expect(run?.status).toBe('completed')
  expect(run?.dataset_dir).toContain(`/_datasets/${name}`)

  // Create project from this → the import wizard on the dataset (metadata-v1)
  await dialog.getByRole('button', { name: 'Create project from this' }).click()
  const create = page.getByRole('dialog', { name: 'New project' })
  await create.getByLabel('Project name').fill(`From ${name}`)
  await create.getByRole('button', { name: 'Create and import' }).click()
  await expect(page).toHaveURL(/\/p\/[0-9A-Z]{26}/)
  const pid = /\/p\/([0-9A-Z]{26})/.exec(page.url())?.[1] ?? ''
  const wizard = page.getByRole('dialog', { name: 'Import data' })
  await expect(wizard.getByRole('radio', { name: /Metadata table/ })).toBeChecked()
  await wizard.getByRole('button', { name: 'Next' }).click()
  await wizard.getByRole('button', { name: 'Import and index' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Import finished' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('tree', { name: 'Project' }).getByRole('treeitem', { name: /case_00000/ })).toBeVisible()
  const project = (await (await fetch(`${API}/projects/${pid}`)).json()) as { packs: string[]; annotation_sources: Record<string, string | null> }
  expect(project.packs).toEqual([]) // neutral
  expect(project.annotation_sources.phase).toBeTruthy() // the chained phase analyzer's layer
})

test('a folder without DICOM is refused with the cause and next steps (UI-18, AUD-A2-07)', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /Convert DICOM/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Convert DICOM' })
  const folders = dialog.getByRole('listbox', { name: 'Folders' })
  await folders.getByRole('button', { name: /synthetic/ }).click()
  await folders.getByRole('button', { name: /Dataset900/ }).click()
  await folders.getByRole('button', { name: /^nifti$/ }).click()
  await dialog.getByRole('button', { name: 'Next' }).click()
  await dialog.getByRole('button', { name: 'Dry run' }).click()
  const alert = dialog.getByRole('alert')
  await expect(alert).toContainText(/No DICOM files in nifti; \d+ NIfTI files found/)
  await expect(alert.getByRole('button', { name: 'Create project from this' })).toBeVisible()
  await alert.getByRole('button', { name: 'Open without a project' }).click()
  await expect(page).toHaveURL(/\/open\/[0-9A-Z]{26}$/)
})
