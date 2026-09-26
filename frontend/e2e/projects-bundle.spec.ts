// Step 3b project actions on the real backend: full hashes (API-15, IMP-09) through the jobs UI,
// bundle export (PRJ-08) and import with its resolve report (PRJ-09, API-06).
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

import { expect, test } from '@playwright/test'

const API = `http://127.0.0.1:${process.env.E2E_API_PORT ?? 8011}/api/v1`
const DATASET = resolve(import.meta.dirname, '../../.fixtures/synthetic/Dataset900')

async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, { method, headers: { 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${await r.text()}`)
  return (await r.json()) as T
}

let pid = ''
let name = ''

test.beforeAll(async () => {
  name = `Bundle ${Date.now()}`
  pid = (await api<{ project_id: string }>('POST', '/projects', { name, packs: ['ccrcc'] })).project_id
  const pv = await api<{ preview_id: string }>('POST', `/projects/${pid}/imports/preview`, { root: DATASET, alias: 'DATA', detect: true })
  await api('POST', `/projects/${pid}/imports`, { preview_id: pv.preview_id })
  await expect
    .poll(async () => (await api<{ index: { state: string } }>('GET', `/projects/${pid}/imports`)).index.state, { timeout: 30_000 })
    .toBe('ready')
})

test('compute full hashes: job in the Jobs panel, then up to date', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto(`/p/${pid}`)
  const action = page.getByRole('button', { name: /Compute full hashes/ })
  await action.click()
  await expect(page.getByRole('status').filter({ hasText: /Hashing \d+ files/ })).toBeVisible()
  const jobs = page.getByRole('tabpanel').filter({ has: page.getByRole('columnheader', { name: 'Job' }) })
  const row = jobs.getByRole('row').filter({ hasText: 'Full hash' }).first()
  await expect(row).toBeVisible()
  await expect(row).toContainText('Completed', { timeout: 90_000 }) // one run-state vocabulary (AUD-A3-10)
  // Results land on the item records (API-21/22)
  const item = await api<{ image: { sha256?: string | null } | null }>('GET', `/projects/${pid}/items/${encodeURIComponent('case_00001.01.complete.-')}`)
  expect(item.image?.sha256).toMatch(/^[0-9a-f]{64}$/)
  // A second run has nothing to do
  await action.click()
  await expect(page.getByRole('status').filter({ hasText: /Full hashes are up to date/ })).toBeVisible()
})

test('bundle export downloads a zip; import shows the resolve report and opens the copy', async ({ page }) => {
  await page.goto('/')
  const card = page.getByRole('listitem').filter({ hasText: name })
  const [download] = await Promise.all([page.waitForEvent('download'), card.getByRole('button', { name: 'Export project bundle' }).click()])
  expect(download.suggestedFilename()).toMatch(/\.zip$/)
  const zip = join(mkdtempSync(join(tmpdir(), 'rw-bundle-')), download.suggestedFilename())
  await download.saveAs(zip)

  await page.getByLabel('Import project bundle…').setInputFiles(zip)
  const dialog = page.getByRole('dialog', { name: 'Import project bundle' })
  await expect(dialog.getByText(`Imported ${name}.`)).toBeVisible()
  // Same workspace: the id is taken, so the copy gets a new one; the data root resolves here
  await expect(dialog.getByText(/already had project/)).toBeVisible()
  const data = dialog.getByRole('row').filter({ hasText: 'DATA' })
  await expect(data).toContainText(/sampled items match · 0 changed · 0 missing/)
  await expect(dialog.getByRole('button', { name: 'Relink data root…' })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Open project' }).click()
  await expect(page).toHaveURL(/\/p\/[0-9A-Z]{26}/)
  expect(page.url()).not.toContain(pid)
  await expect(page.getByRole('tree', { name: 'Project' }).getByRole('treeitem', { name: /case_00001/ })).toBeVisible({ timeout: 30_000 })
})

// PRJ-06, API-04 (AUD-A4-03): archive from the home card with a confirmation, restore from the
// Archived list; File › Archive project… inside a project returns to the home
test('archive and restore a project from the home', async ({ page }) => {
  const other = `Archive ${Date.now()}`
  const oid = (await api<{ project_id: string }>('POST', '/projects', { name: other })).project_id
  await page.goto('/')
  const card = page.getByRole('listitem').filter({ hasText: other })
  await card.getByRole('button', { name: 'Archive project…' }).click()
  const dialog = page.getByRole('dialog', { name: `Archive “${other}”?` })
  await dialog.getByRole('button', { name: 'Archive', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: `“${other}” archived` })).toBeVisible()
  await expect(card).toHaveCount(0)
  await page.getByRole('button', { name: 'Archived', exact: true }).click()
  const archived = page.getByRole('list', { name: 'Archived projects' }).getByRole('listitem').filter({ hasText: other })
  await archived.getByRole('button', { name: 'Restore' }).click()
  await expect(page.getByRole('status').filter({ hasText: `“${other}” restored` })).toBeVisible()
  await page.getByRole('button', { name: 'Archived', exact: true }).click()
  await expect(page.getByRole('listitem').filter({ hasText: other })).toBeVisible()

  // From inside the project: File › Archive project…
  await page.goto(`/p/${oid}`)
  await page.getByRole('navigation', { name: 'Application menu' }).getByRole('button', { name: 'File' }).click()
  await page.getByRole('menuitem', { name: 'Archive project…' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Archive', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
  expect((await api<{ project_id: string }[]>('GET', '/projects?archived=true')).map((p) => p.project_id)).toContain(oid)
})
