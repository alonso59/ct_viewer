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
  const detection = page.waitForResponse((r) => r.url().endsWith('/sources/detect') && r.request().method() === 'POST', { timeout: 30_000 })
  await create.getByRole('button', { name: 'Create and import' }).click()
  expect((await detection).ok()).toBe(true)
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

test('UI-28 re-estimates and restores the same minimized operation after browser reload', async ({ page, browserName }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /Convert DICOM/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Convert DICOM' })
  const folders = dialog.getByRole('listbox', { name: 'Folders' })
  await folders.getByRole('button', { name: /synthetic/ }).click()
  await folders.getByRole('button', { name: /^dicom$/ }).click()
  await dialog.getByRole('button', { name: 'Next' }).click()
  const started = page.waitForResponse((r) => r.url().endsWith('/source-operations') && r.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Dry run' }).click()
  const operation = await (await started).json() as { operation_id: string }
  await expect(dialog.getByRole('button', { name: /Convert \d+ series/ })).toBeVisible()
  const url = `${API}/source-operations/${operation.operation_id}`
  const original = await (await page.request.get(url)).json() as { summary: { generation: string }; plan_attempt: number }
  const name = `revised-${browserName}-${Date.now()}`
  await dialog.getByRole('button', { name: 'Back', exact: true }).click()
  await dialog.getByLabel('Dataset name').fill(name)
  await dialog.getByRole('checkbox', { name: /phase analyzer/ }).uncheck()
  const estimated = page.waitForResponse((r) => r.url() === `${url}/estimate` && r.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Dry run' }).click()
  expect((await estimated).ok()).toBe(true)
  await expect(dialog.getByRole('button', { name: /Convert \d+ series/ })).toBeVisible()
  const revised = await (await page.request.get(url)).json() as { operation_id: string; summary: { generation: string }; plan_attempt: number; dataset_name: string; settings: { phase_analyzer: boolean } }
  expect(revised.operation_id).toBe(operation.operation_id)
  expect(revised.summary.generation).toBe(original.summary.generation)
  expect(revised.plan_attempt).toBeGreaterThan(original.plan_attempt)
  expect(revised.dataset_name).toBe(name)
  expect(revised.settings.phase_analyzer).toBe(false)
  await dialog.getByRole('button', { name: 'Minimize', exact: true }).click()
  await expect(page.getByTestId('conv-chip')).toBeVisible()
  await page.reload()
  const chip = page.getByTestId('conv-chip')
  await expect(chip).toBeVisible()
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('rw.converter') ?? '{}') as { state: Record<string, unknown> })
  expect(stored.state).toEqual({ operationId: operation.operation_id, minimized: true })
  await chip.getByRole('button', { name: 'Show', exact: true }).click()
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: /Convert \d+ series/ })).toBeVisible()
  await expect(dialog.getByRole('table')).toBeVisible()
  await dialog.getByRole('button', { name: 'Back', exact: true }).click()
  await expect(dialog.getByLabel('Dataset name')).toHaveValue(name)
  await expect(dialog.getByRole('checkbox', { name: /phase analyzer/ })).not.toBeChecked()
})
