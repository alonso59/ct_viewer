// TST-08 (ops/TESTING.md): two reviewers in two browser contexts on the same case.
// CUR-11: a decision by A reaches B over SSE ("updated by" toast + new state).
// CUR-12: concurrent writes to the same (item, target) → last writer wins everywhere; history keeps both.
// CUR-08 (AUD-A5-15, A5-09, A2-16): a case with one decided item of several is "Partially reviewed",
// the Search Status filter finds it on the real API, the queue CSV names the segmentation set.
// Real backend on the synthetic fixtures (playwright.config.ts starts it); setup goes through the API.

import { expect, test, type Browser, type Page } from '@playwright/test'

import { api, API, importedProject } from './helpers'

const CASE = 'case_00002'
const ITEM = 'case_00002.01.complete.-'

interface TargetState { target: string; status: string; reviewer: string }
interface CurationState { n_events: number; items: { item_id: string; targets: TargetState[] }[] }

let pid = ''

async function newProject() {
  pid = await importedProject(`TST-08 ${Date.now()}`)
}

/** A browser context with a preset reviewer name (CUR-01 stamp in localStorage) on the case */
async function reviewer(browser: Browser, name: string): Promise<Page> {
  const ctx = await browser.newContext()
  await ctx.addInitScript((n) => {
    localStorage.setItem('rw.reviewer', JSON.stringify({ state: { name: n }, version: 0 }))
  }, name)
  const page = await ctx.newPage()
  await page.goto(`/p/${pid}/case/${CASE}?item=${encodeURIComponent(ITEM)}`)
  await page.getByRole('navigation', { name: 'Activity bar' }).getByRole('button', { name: 'Curation' }).click()
  // the form names the item on screen (AUD-A1-13: `case · phase · scope`, the id in its title)
  await expect(page.getByRole('complementary', { name: 'Curation' }).locator(`[title="${ITEM}"]`).first()).toBeVisible()
  await expect(page.getByRole('contentinfo', { name: 'Status bar' }).getByText('live', { exact: true }).first()).toBeVisible({ timeout: 30_000 })
  return page
}
// Firefox fires EventSource `open` only on the first body bytes, i.e. the first 15 s ping (open issue)
test.setTimeout(120_000)

const form = (page: Page) => page.getByRole('complementary', { name: 'Curation' })
const decisions = (page: Page) => form(page).getByRole('list', { name: 'Current decisions' })
const segRow = (page: Page) => decisions(page).getByRole('listitem').filter({ hasText: /^seg/ })
const quick = (page: Page, label: RegExp) => form(page).getByRole('button', { name: label })

test('live sync and last-writer-wins between two reviewers', async ({ browser }) => {
  await newProject()
  const a = await reviewer(browser, 'Dr. A')
  const b = await reviewer(browser, 'Dr. B')

  // CUR-11: A accepts the segmentation; B gets the toast and the new state without reloading
  await quick(a, /^Accept/).click()
  await expect(segRow(a)).toContainText('Accepted')
  await expect(b.getByRole('status').filter({ hasText: `${CASE} updated by Dr. A: Accepted` })).toBeVisible()
  // The toast proves the SSE event arrived; the row follows B's refetch, which can queue behind
  // the thumbnail job right after indexing. An event during B's first state load restarts that load
  // (AUD-A0-02, unit-tested in api/liveState.test.ts)
  await expect(segRow(b)).toContainText('Accepted', { timeout: 15_000 })
  // A's own event does not toast "updated by" in A's tab (same session)
  await expect(a.getByRole('status').filter({ hasText: 'updated by' })).toHaveCount(0)

  // CUR-12: both write the same (item, target) at once; the server keeps the last one
  await Promise.all([quick(a, /^Minor/).click(), quick(b, /^Reject/).click()])
  // Wait until both writes are in (3 events), then read the derived winner
  await expect.poll(async () => (await api<{ n_events: number }>('GET', `/projects/${pid}/curation/state`)).n_events).toBe(3)
  const st = await api<CurationState>('GET', `/projects/${pid}/curation/state`)
  const last = st.items.find((i) => i.item_id === ITEM)?.targets.find((x) => x.target === 'seg')
  expect(last?.status).toMatch(/needs_minor_correction|rejected/)
  const shown = last?.status === 'rejected' ? 'Rejected' : 'Needs minor correction'
  for (const page of [a, b]) await expect(segRow(page)).toContainText(shown)
  expect(last?.reviewer).toBe(last?.status === 'rejected' ? 'Dr. B' : 'Dr. A')

  // History (CUR-14) shows every event, newest first, in both tabs
  for (const page of [a, b]) {
    await page.getByRole('navigation', { name: 'Activity bar' }).getByRole('button', { name: 'History' }).click()
    const events = page.getByRole('list', { name: 'Curation events' }).getByRole('listitem')
    await expect(events).toHaveCount(3)
    await expect(events.first()).toContainText(shown)
    await expect(events.filter({ hasText: 'Dr. A' })).toHaveCount(2)
    await expect(events.filter({ hasText: 'Dr. B' })).toHaveCount(1)
  }
  await a.context().close()
  await b.context().close()
})

test('partial rollup, Search status filter and queue CSV with seg_id', async ({ browser }) => {
  await newProject()
  const cases = await api<{ items: { case_id: string; n_items_active: number }[] }>('GET', `/projects/${pid}/cases?limit=200`)
  const multi = cases.items.find((c) => c.n_items_active > 1)
  expect(multi).toBeTruthy()
  const caseId = multi?.case_id ?? ''
  const ctx = await browser.newContext()
  await ctx.addInitScript(() => localStorage.setItem('rw.reviewer', JSON.stringify({ state: { name: 'Dr. A' }, version: 0 })))
  const page = await ctx.newPage()
  await page.goto(`/p/${pid}/case/${caseId}`)
  const activity = page.getByRole('navigation', { name: 'Activity bar' })
  await activity.getByRole('button', { name: 'Curation' }).click()
  await expect(form(page).locator(`[title^="${caseId}."]`).first()).toBeVisible() // the item on screen (AUD-A1-13)
  await quick(page, /^Accept/).click()
  await expect(segRow(page)).toContainText('Accepted')
  // AUD-A5-15: one item of several decided → partial, and not counted as reviewed
  const header = page.locator('.case-header')
  await expect(header.getByText('Partially reviewed', { exact: true })).toBeVisible({ timeout: 15_000 })
  const listed = await api<{ project_id: string; curation_progress: number }[]>('GET', '/projects')
  expect(listed.find((p) => p.project_id === pid)?.curation_progress).toBe(0)

  // AUD-A5-09: the Search view's Status filters on the rollup through API-20 (no 422)
  await activity.getByRole('button', { name: 'Search' }).click()
  const search = page.getByRole('complementary', { name: 'Search' })
  await search.getByLabel('Curation status').selectOption('partially_reviewed')
  await expect(search.getByText('1 case', { exact: true })).toBeVisible()
  await search.getByLabel('Curation status').selectOption('not_reviewed')
  await expect(search.getByText(`${cases.items.length - 1} cases`, { exact: true })).toBeVisible()

  // AUD-A2-16: the correction-queue CSV names the set of a mask decision
  await activity.getByRole('button', { name: 'Curation' }).click()
  await quick(page, /^Reject/).click()
  await expect(segRow(page)).toContainText('Rejected')
  const csv = await (await fetch(`${API}/projects/${pid}/curation/queue?format=csv`)).text()
  expect(csv.split('\n')[0]).toContain(',target,seg_id,status,')
  expect(csv).toContain(',seg,imported,rejected,')
  await ctx.close()
})
