// P7b Wave 3 exit points on the real backend: a single DICOM file opens in Open mode and saves as
// NIfTI (SRC-13/14); a DICOM folder converts into a project from the Tasks tab (DCM-*, UI-20).
import { expect, test } from '@playwright/test'

import { gotoOpen } from './openMode'
import { api, FIXTURES } from './helpers'

const DICOM = `${FIXTURES}/dicom`

test('a single DICOM file opens without a project and saves as NIfTI', async ({ page }) => {
  await gotoOpen(page, `${DICOM}/P900/ct_np/IM0007.dcm`)
  await expect(page.getByText('No project: nothing is saved')).toBeVisible()
  await expect(page.getByRole('listbox', { name: 'Files' }).getByRole('button', { name: /IM0007/ })).toBeVisible()
  await page.getByRole('button', { name: 'Save as NIfTI…' }).click()
  const dialog = page.getByRole('dialog', { name: /Save IM0007/ })
  await expect(dialog.getByText(/_open\/\d{4}-\d{2}-\d{2}/)).toBeVisible()
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  // the series converts in a job worker, which may queue behind thumbnails of other projects
  await expect(page.getByRole('status').filter({ hasText: /Saved .*ct_np(-\d+)?\.nii\.gz/ })).toBeVisible({ timeout: 30_000 })
})

test('a DICOM folder converts into a project from the Tasks tab', async ({ page }) => {
  const p = await api<{ project_id: string }>('POST', '/projects', { name: `DICOM ${Date.now()}`, packs: ['ccrcc'] })
  await api('PUT', `/projects/${p.project_id}/roots/DERIVED`, { path: process.env.E2E_DERIVED, role: 'derived' })
  await page.goto(`/p/${p.project_id}/tasks/dicom.convert`)
  await expect(page.getByRole('heading', { name: 'DICOM → NIfTI' })).toBeVisible()
  const folders = page.getByRole('listbox', { name: 'Folders' })
  await folders.getByRole('button', { name: /synthetic/ }).click()
  await folders.getByRole('button', { name: /^dicom$/ }).click()
  await expect(page.getByText('1 of 1 ready')).toBeVisible()
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  await expect(page.locator('.task-run').first().getByText('Completed', { exact: true })).toBeVisible({ timeout: 45_000 })
  await expect
    .poll(async () => (await api<{ items: { case_id: string }[] }>('GET', `/projects/${p.project_id}/cases`)).items.map((c) => c.case_id), { timeout: 30_000 })
    .toEqual(['case_00000', 'case_00001'])
  const item = await api<{ phase: { canonical: string; source: string }; extra: Record<string, unknown> }>('GET', `/projects/${p.project_id}/items/case_00000.01.complete.-`)
  expect(item.phase.source).toMatch(/^analyzer:/)
  expect(item.extra.dicom_sidecar).toBeTruthy()
})

test('the import wizard converts a DICOM folder with the anonymize choice', async ({ page }) => {
  // AUD-A5-16 (DCM-05, NFR-17): the wizard's in-project conversion offers `anonymize: basic`
  const p = await api<{ project_id: string }>('POST', '/projects', { name: `Wizard DICOM ${Date.now()}`, packs: ['ccrcc'] })
  await api('PUT', `/projects/${p.project_id}/roots/DERIVED`, { path: process.env.E2E_DERIVED, role: 'derived' })
  await page.goto(`/p/${p.project_id}`)
  await page.keyboard.press('ControlOrMeta+Shift+p')
  await page.getByRole('dialog').getByRole('combobox').fill('Import data')
  await page.getByRole('dialog').getByRole('option', { name: /Import data/ }).click()
  const wizard = page.getByRole('dialog', { name: 'Import data' })
  const folders = wizard.getByRole('listbox', { name: 'Folders' })
  await folders.getByRole('button', { name: /synthetic/ }).click()
  await folders.getByRole('button', { name: /^dicom$/ }).click()
  await wizard.getByRole('button', { name: 'Next' }).click()
  await wizard.getByRole('radio', { name: /DICOM → NIfTI conversion/ }).check()
  await wizard.getByRole('checkbox', { name: /Anonymize/ }).check()
  await wizard.getByRole('button', { name: 'Next' }).click()
  await expect
    .poll(async () => (await api<{ items: { case_id: string }[] }>('GET', `/projects/${p.project_id}/cases`)).items.map((c) => c.case_id), { timeout: 60_000 })
    .toEqual(['case_00000', 'case_00001'])
  const iid = 'case_00000.01.complete.-'
  const item = await api<{ patient_id: string | null }>('GET', `/projects/${p.project_id}/items/${iid}`)
  expect(item.patient_id).toBe('case_00000')
  const tags = await api<Record<string, { Value?: unknown[] }>>('GET', `/projects/${p.project_id}/items/${iid}/dicom-tags`)
  expect(tags['00120062']?.Value).toEqual(['YES']) // PatientIdentityRemoved
})
