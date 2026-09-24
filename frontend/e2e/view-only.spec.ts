// TST-18 (PRJ-17, UI-26): a view-only link opens the project read-only; editing controls, views and
// shortcuts are hidden, and the server has no write route on that path. Real backend.
import { resolve } from 'node:path'

import { expect, test } from '@playwright/test'

const API = `http://127.0.0.1:${process.env.E2E_API_PORT ?? 8011}/api/v1`
const DATASET = resolve(import.meta.dirname, '../../.fixtures/synthetic/Dataset900')

async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, { method, headers: { 'content-type': 'application/json', 'X-Reviewer': 'E2E' }, body: body === undefined ? undefined : JSON.stringify(body) })
  if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${await r.text()}`)
  return (r.status === 204 ? null : await r.json()) as T
}

test('a view-only link cannot write and hides every editing control', async ({ page }) => {
  const p = await api<{ project_id: string }>('POST', '/projects', { name: `View ${Date.now()}`, packs: ['ccrcc'] })
  const pid = p.project_id
  const pv = await api<{ preview_id: string }>('POST', `/projects/${pid}/imports/preview`, { root: DATASET, alias: 'DATA', detect: true })
  await api('POST', `/projects/${pid}/imports`, { preview_id: pv.preview_id })
  await expect.poll(async () => (await api<{ index: { state: string } }>('GET', `/projects/${pid}/imports`)).index.state, { timeout: 30_000 }).toBe('ready')
  const { view_token: token } = await api<{ view_token: string }>('POST', `/projects/${pid}/view-token`)

  await page.goto(`/v/${token}`)
  await expect(page.getByText('View only', { exact: true })).toBeVisible()
  expect(page.url()).not.toContain(pid)
  const bar = page.getByRole('navigation', { name: 'Activity bar' })
  await expect(bar.getByRole('button', { name: 'Project', exact: true })).toBeVisible()
  for (const view of ['Curation', 'Tasks', 'Radiomics', 'Variables', 'Plugin Library']) await expect(bar.getByRole('button', { name: view, exact: true })).toHaveCount(0)

  // The viewer works; the curation shortcut does nothing
  const row = page.getByRole('tree', { name: 'Project' }).getByRole('treeitem', { name: /case_00001/ })
  await row.dblclick()
  await expect(page.locator('.vp').first()).toBeVisible()
  await page.locator('.vp').first().click()
  await page.keyboard.press('a')
  await page.keyboard.press('ControlOrMeta+Alt+b')
  await expect(page.locator('.inspector')).toBeVisible()
  await expect(page.locator('.inspector .section-title', { hasText: 'Curation' })).toHaveCount(0)

  // The palette lists no write commands
  await page.keyboard.press('ControlOrMeta+Shift+p')
  const palette = page.getByRole('dialog')
  await palette.getByRole('combobox').fill('project settings')
  await expect(palette.getByRole('option', { name: /Project settings/ })).toHaveCount(0)
  await page.keyboard.press('Escape')

  // Server side: no writes on the view prefix, and nothing was recorded
  const post = await fetch(`${API}/view/${token}/curation/events`, { method: 'POST', headers: { 'content-type': 'application/json', 'X-Reviewer': 'E2E' }, body: JSON.stringify({ item_id: 'case_00001.01.complete.-', target: 'seg', status: 'accepted' }) })
  expect(post.status).toBe(405)
  expect((await api<{ total: number }>('GET', `/projects/${pid}/curation/events`)).total).toBe(0)

  // Revoking the token closes the link
  await api('DELETE', `/projects/${pid}/view-token`)
  expect((await fetch(`${API}/view/${token}`)).status).toBe(404)
})
