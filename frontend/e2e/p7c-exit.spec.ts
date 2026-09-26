// P7c exit criterion (ROADMAP §P7c), one user journey on the real backend: convert a DICOM folder
// without a project (overlay) → open the dataset with the CT tools → create a neutral project from
// it → apply the ccRCC pack → label in a patient-level and a CT-level table → curate an item →
// share a view-only link that cannot write; every plugin opens from the Library.
import { expect, test, type Page } from '@playwright/test'

const API = `http://127.0.0.1:${process.env.E2E_API_PORT ?? 8011}/api/v1`
const json = async <T,>(r: Response) => (await r.json()) as T

const cell = (page: Page, row: number, col: number) => page.getByRole('row').filter({ has: page.getByRole('rowheader') }).nth(row).getByRole('gridcell').nth(col)

test('the P7c journey', async ({ page, browserName }) => {
  test.setTimeout(180_000)
  await page.addInitScript(() => localStorage.setItem('rw.reviewer', JSON.stringify({ state: { name: 'Dr. Exit' }, version: 0 })))
  const name = `exit-${browserName}-${Date.now()}`

  // 1 · Convert without a project from the converter overlay
  await page.goto('/')
  await page.getByRole('button', { name: /Convert DICOM/ }).click()
  const conv = page.getByRole('dialog', { name: 'Convert DICOM' })
  const folders = conv.getByRole('listbox', { name: 'Folders' })
  await folders.getByRole('button', { name: /synthetic/ }).click()
  await folders.getByRole('button', { name: /^dicom$/ }).click()
  await conv.getByRole('button', { name: 'Next' }).click()
  await conv.getByLabel('Dataset name').fill(name)
  await conv.getByRole('button', { name: 'Dry run' }).click()
  await conv.getByRole('button', { name: /Convert \d+ series/ }).click()
  await conv.getByRole('button', { name: 'Show the result' }).click({ timeout: 60_000 })

  // 2 · Open the dataset: the full CT tool set, no project
  await conv.getByRole('button', { name: 'Open', exact: true }).click()
  await expect(page).toHaveURL(/\/open\/[0-9A-Z]{26}$/) // the session id, never the path (AUD-A1-19)
  expect(page.url()).not.toContain('_datasets')
  await expect(page.getByText('No project: nothing is saved')).toBeVisible()
  const tools = page.getByRole('toolbar').filter({ has: page.getByRole('button', { name: 'Invert' }) })
  for (const b of ['Distance', 'Header info', 'Slab projection', 'Screenshot (PNG)']) await expect(tools.getByRole('button', { name: b })).toBeVisible()
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })

  // 3 · Create a neutral project from it
  await page.getByRole('button', { name: 'Create project from this' }).click()
  const create = page.getByRole('dialog', { name: 'New project' })
  await create.getByLabel('Project name').fill(`Project ${name}`)
  await create.getByRole('button', { name: 'Create and import' }).click()
  await expect(page).toHaveURL(/\/p\/[0-9A-Z]{26}/)
  const pid = /\/p\/([0-9A-Z]{26})/.exec(page.url())?.[1] ?? ''
  const wizard = page.getByRole('dialog', { name: 'Import data' })
  await expect(wizard.getByRole('radio', { name: /Metadata table/ })).toBeChecked()
  await wizard.getByRole('button', { name: 'Next' }).click()
  await wizard.getByRole('button', { name: 'Import and index' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Import finished' })).toBeVisible({ timeout: 30_000 })
  expect((await json<{ packs: string[] }>(await fetch(`${API}/projects/${pid}`))).packs).toEqual([])

  // 4 · Apply the ccRCC pack from Project settings › Plugins
  await page.keyboard.press('ControlOrMeta+Shift+p')
  await page.getByRole('dialog').getByRole('combobox').fill('Project settings')
  await page.getByRole('dialog').getByRole('option', { name: /Project settings/ }).click()
  await page.getByRole('tab', { name: 'Plugins' }).click()
  await page.locator('[data-pack="ccrcc"]').getByRole('button', { name: 'Apply' }).click()
  await expect(page.locator('[data-pack="ccrcc"]').getByText('applied')).toBeVisible()

  // 5 · Label in a patient-level and a CT-level table
  for (const [level, label] of [['case', 'Patient'], ['scan', 'CT scan']] as const) {
    const r = await fetch(`${API}/plugins/labeling/projects/${pid}/tables`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: `${label} review`, level, columns: [{ name: 'Usable', type: 'bool' }] }) })
    const t = await json<{ table_id: string }>(r)
    await page.goto(`/p/${pid}/labeling/${t.table_id}`)
    await cell(page, 0, 0).click()
    await page.keyboard.press(' ')
    await expect(cell(page, 0, 0)).toHaveText('✓')
  }

  // 6 · Curate an item
  await page.goto(`/p/${pid}/case/case_00000`)
  await page.getByRole('navigation', { name: 'Activity bar' }).getByRole('button', { name: 'Curation' }).click()
  await page.getByRole('complementary', { name: 'Curation' }).getByRole('button', { name: /^Accept/ }).click()
  await expect.poll(async () => (await json<{ n_events: number }>(await fetch(`${API}/projects/${pid}/curation/state`))).n_events).toBe(1)

  // 7 · Every plugin is reachable from the Library (pending ones are listed, not openable)
  await page.getByRole('navigation', { name: 'Activity bar' }).getByRole('button', { name: 'Plugin Library' }).click()
  const lib = page.locator('.plugin-list')
  for (const id of ['dicom', 'analyzers', 'curation', 'labeling', 'radiomics', 'dashboard', 'ccrcc', 'generic-ct'])
    await expect(lib.locator(`[data-plugin="${id}"]`).getByRole('button', { name: /^Open / })).toBeEnabled()
  for (const id of ['nnunet', 'voi']) await expect(lib.locator(`[data-plugin="${id}"]`).getByRole('button', { name: /^Open / })).toBeDisabled()

  // 8 · A view-only link that cannot write
  const { view_token } = await json<{ view_token: string }>(await fetch(`${API}/projects/${pid}/view-token`, { method: 'POST' }))
  await page.goto(`/v/${view_token}`)
  await expect(page.getByText('View only', { exact: true })).toBeVisible()
  const post = await fetch(`${API}/view/${view_token}/curation/events`, { method: 'POST', headers: { 'content-type': 'application/json', 'X-Reviewer': 'x' }, body: JSON.stringify({ item_id: 'case_00000.01.complete.-', target: 'seg', status: 'accepted' }) })
  expect(post.status).toBe(405)
  // ADR-0026: native phase selection is a write too
  const phase = await fetch(`${API}/view/${view_token}/phase/events`, { method: 'POST', headers: { 'content-type': 'application/json', 'X-Reviewer': 'x' }, body: JSON.stringify({ case_id: 'case_00000', scan_idx: '01', value: 'NP' }) })
  expect(phase.status).toBe(405)
})
