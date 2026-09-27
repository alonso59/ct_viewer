// TST-18 (PRJ-17, UI-26): a view-only link opens the project read-only; editing controls, views and
// shortcuts are hidden, and the server has no write route on that path. Real backend.
// AUD-A5-03: nothing the page reads through the token carries the project id or a server path.

import { expect, test } from '@playwright/test'

import { api, API, DATASET, importedProject } from './helpers'

test('a view-only link cannot write and hides every editing control', async ({ page }) => {
  const pid = await importedProject(`View ${Date.now()}`)
  const { view_token: token } = await api<{ view_token: string }>('POST', `/projects/${pid}/view-token`)

  // AUD-A5-03: record what the page reads through the token (JSON and CSV; SSE streams never end)
  const reads: { url: string; body: Promise<string> }[] = []
  page.on('response', (r) => {
    const ct = r.headers()['content-type'] ?? ''
    if (r.url().includes('/api/v1/') && /json|csv/.test(ct)) reads.push({ url: r.url(), body: r.text().catch(() => '') })
  })
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

  // Nothing read through the token carries the project id or an absolute server path; the
  // project's jobs come through the mirror too (`/view/{token}/jobs`)
  expect(reads.map((r) => r.url).filter((u) => u.includes('/api/v1/view/'))).not.toHaveLength(0)
  expect(reads.some((r) => r.url.includes(`/api/v1/view/${token}/jobs`))).toBe(true)
  for (const r of reads) {
    expect(r.url).not.toContain(pid)
    const body = await r.body
    expect(body, r.url).not.toContain(pid)
    expect(body, r.url).not.toContain(DATASET)
  }

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
