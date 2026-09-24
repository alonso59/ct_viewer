// TST-19 (LBL-03..06): two reviewers label the same table; edits appear live in the other browser,
// columns become `lbl.*` variables, and a view-only link shows the table read-only. Real backend.
import { resolve } from 'node:path'

import { expect, test, type Browser, type Page } from '@playwright/test'

const API = `http://127.0.0.1:${process.env.E2E_API_PORT ?? 8011}/api/v1`
const DATASET = resolve(import.meta.dirname, '../../.fixtures/synthetic/Dataset900')

async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, { method, headers: { 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${await r.text()}`)
  return (await r.json()) as T
}

async function reviewer(browser: Browser, name: string, url: string): Promise<Page> {
  const ctx = await browser.newContext()
  await ctx.addInitScript((n) => localStorage.setItem('rw.reviewer', JSON.stringify({ state: { name: n }, version: 0 })), name)
  const page = await ctx.newPage()
  await page.goto(url)
  await expect(page.getByRole('contentinfo', { name: 'Status bar' }).getByText('live', { exact: true }).first()).toBeVisible({ timeout: 30_000 })
  return page
}

const cell = (page: Page, row: number, col: number) => page.getByRole('row').filter({ has: page.getByRole('rowheader') }).nth(row).getByRole('gridcell').nth(col)

test('two reviewers label a patient table live; columns become variables', async ({ browser }) => {
  test.setTimeout(120_000)
  const p = await api<{ project_id: string }>('POST', '/projects', { name: `Labeling ${Date.now()}`, packs: ['ccrcc'] })
  const pid = p.project_id
  const pv = await api<{ preview_id: string }>('POST', `/projects/${pid}/imports/preview`, { root: DATASET, alias: 'DATA', detect: true })
  await api('POST', `/projects/${pid}/imports`, { preview_id: pv.preview_id })
  await expect.poll(async () => (await api<{ index: { state: string } }>('GET', `/projects/${pid}/imports`)).index.state, { timeout: 30_000 }).toBe('ready')
  const t = await api<{ table_id: string }>('POST', `/plugins/labeling/projects/${pid}/tables`, {
    name: 'Review', level: 'case', columns: [{ name: 'Grade', type: 'category', levels: ['G1', 'G2', 'G3'] }, { name: 'Tumour', type: 'bool' }],
  })
  const url = `/p/${pid}/labeling/${t.table_id}`
  const a = await reviewer(browser, 'Dr. A', url)
  const b = await reviewer(browser, 'Dr. B', url)

  // A sets a category with the keyboard editor; B sees it without reloading (LBL-05)
  await cell(a, 0, 0).click()
  await a.keyboard.press('Enter')
  await a.getByRole('combobox', { name: 'Grade' }).selectOption('G2')
  await expect(cell(a, 0, 0)).toHaveText('G2')
  await expect(cell(b, 0, 0)).toHaveText('G2', { timeout: 15_000 })
  // B toggles a yes/no cell with Space; A sees it
  await cell(b, 1, 1).click()
  await b.keyboard.press(' ')
  await expect(cell(a, 1, 1)).toHaveText('✓', { timeout: 15_000 })
  // History of the cell shows the reviewer (LBL-04)
  await cell(a, 1, 1).click()
  await expect(a.getByRole('complementary', { name: 'Cell history' })).toContainText('Dr. B')

  // LBL-06: the column is a typed variable
  await expect.poll(async () => (await api<{ variables: { name: string; type: string }[] }>('GET', `/projects/${pid}/variables`)).variables.find((v) => v.name === 'lbl.review.grade')?.type, { timeout: 15_000 }).toBe('categorical')

  // A view-only link shows the table, read-only
  const { view_token } = await api<{ view_token: string }>('POST', `/projects/${pid}/view-token`)
  const v = await a.context().newPage()
  await v.goto(`/v/${view_token}`)
  await v.getByRole('navigation', { name: 'Activity bar' }).getByRole('button', { name: 'Labeling' }).click()
  await v.getByRole('complementary', { name: 'Labeling' }).getByRole('button', { name: /^Review/ }).click()
  await expect(v.getByText('Read only', { exact: true })).toBeVisible()
  await expect(cell(v, 0, 0)).toHaveText('G2')
  await cell(v, 2, 1).click()
  await v.keyboard.press(' ')
  await expect(cell(v, 2, 1)).toHaveText('')
  await a.context().close()
  await b.context().close()
})
