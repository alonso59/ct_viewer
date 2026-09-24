// P7b Wave 3 exit points on the real backend: a single DICOM file opens in Open mode and saves as
// NIfTI (SRC-13/14); a DICOM folder converts into a project from the Tasks tab (DCM-*, UI-20).
import { resolve } from 'node:path'

import { expect, test } from '@playwright/test'

const API = `http://127.0.0.1:${process.env.E2E_API_PORT ?? 8011}/api/v1`
const DICOM = resolve(import.meta.dirname, '../../.fixtures/synthetic/dicom')

async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, { method, headers: { 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${await r.text()}`)
  return (await r.json()) as T
}

test('a single DICOM file opens without a project and saves as NIfTI', async ({ page }) => {
  await page.goto(`/open?path=${encodeURIComponent(`${DICOM}/P900/ct_np/IM0007.dcm`)}`)
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
  await expect(page.locator('.task-run').first().getByText('completed', { exact: true })).toBeVisible({ timeout: 45_000 })
  await expect
    .poll(async () => (await api<{ items: { case_id: string }[] }>('GET', `/projects/${p.project_id}/cases`)).items.map((c) => c.case_id), { timeout: 30_000 })
    .toEqual(['case_00000', 'case_00001'])
  const item = await api<{ phase: { canonical: string; source: string }; extra: Record<string, unknown> }>('GET', `/projects/${p.project_id}/items/case_00000.01.complete.-`)
  expect(item.phase.source).toMatch(/^analyzer:/)
  expect(item.extra.dicom_sidecar).toBeTruthy()
})
