// NFR-12 network allowlist (REL-06; FE-06, BE-11, AGENTS R5; AUD-A4-02): across a journey that
// touches every kind of screen — Home, Open mode with the viewer, a project with a case tab (2D +
// 3D mesh), radiomics, the correction queue, project settings and a run
// dashboard — the browser requests nothing outside the app's own origin. Every request of the
// context (pages and workers) and every WebSocket is recorded; a foreign one is aborted so it can
// never leave the machine, and fails the test. Real backend on the synthetic fixtures.
import { resolve } from 'node:path'

import { expect, test, type Page } from '@playwright/test'

import { gotoOpen } from './openMode'
import { api, DATASET, importedProject } from './helpers'

const IMAGE = resolve(DATASET, 'nifti/01_case_00030_0000.nii.gz')
// Not network: inline data and object URLs the app creates itself
const LOCAL_SCHEMES = new Set(['data:', 'blob:', 'about:'])

/** Let the screen finish its lazy loads (chunks, workers, fonts) before moving on */
async function settle(page: Page) {
  await page.waitForLoadState('networkidle')
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })
}

test.setTimeout(180_000)

test('NFR-12: no request leaves the app origin across a journey', async ({ page, context, baseURL, browserName }) => {
  const origin = new URL(baseURL!).origin
  const wsOrigin = origin.replace(/^http/, 'ws')
  const foreign: string[] = []
  let own = 0
  const isForeign = (url: string) => {
    const u = new URL(url)
    return !LOCAL_SCHEMES.has(u.protocol) && u.origin !== origin
  }
  // Block before the request is sent (route), and record everything the context saw (request)
  await context.route('**/*', (route) => (isForeign(route.request().url()) ? route.abort('blockedbyclient') : route.fallback()))
  context.on('request', (r) => (isForeign(r.url()) ? foreign.push(`${r.method()} ${r.url()}`) : own++))
  page.on('websocket', (ws) => {
    if (new URL(ws.url()).origin.replace(/^http/, 'ws') !== wsOrigin) foreign.push(`WS ${ws.url()}`)
  })

  // Setup through the API (not through the page): a project on the fixtures and a small radiomics run
  const pid = await importedProject(`NFR-12 ${browserName} ${Date.now()}`)
  const items: string[] = []
  for (const cid of ['case_00001', 'case_00002']) {
    const detail = await api<{ scans: { items: { item_id: string }[] }[] }>('GET', `/projects/${pid}/cases/${cid}`)
    items.push(...detail.scans.flatMap((s) => s.items.map((i) => i.item_id)))
  }
  const run = await api<{ run_id: string }>('POST', `/projects/${pid}/task-runs`, {
    task_id: 'radiomics.pyradiomics',
    settings: {},
    selection: { item_ids: items, labels: [2] },
  })

  // Home
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Radiology Workbench' })).toBeVisible()
  await settle(page)

  // Open mode: the NiiVue viewer with its shaders, fonts and colour maps
  await gotoOpen(page, IMAGE)
  await settle(page)
  await expect(page.getByRole('region', { name: 'Axial', exact: true })).toBeVisible()

  // Project view, then a case tab with a mask (2D overlays and the 3D mesh)
  await page.goto(`/p/${pid}`)
  await expect(page.getByRole('tree', { name: 'Project' })).toBeVisible()
  await settle(page)
  await page.goto(`/p/${pid}/case/case_00001`)
  await expect(page.locator('.case-header').getByRole('toolbar', { name: 'Item' })).toBeVisible({ timeout: 30_000 })
  await settle(page)

  // Radiomics, queue, settings; the run finishes meanwhile, then its dashboard
  for (const path of ['radiomics', 'queue', 'settings']) {
    await page.goto(`/p/${pid}/${path}`)
    await settle(page)
  }
  await expect
    .poll(async () => (await api<{ status: string }>('GET', `/projects/${pid}/task-runs/${run.run_id}`)).status, { timeout: 90_000 })
    .toMatch(/^completed/)
  await page.goto(`/p/${pid}/run/${run.run_id}`)
  await expect(page.getByRole('tab', { name: 'Run overview', exact: true })).toBeVisible({ timeout: 30_000 })
  await settle(page)

  expect(own, 'the recorder saw the app’s own requests').toBeGreaterThan(20)
  expect(foreign, 'requests outside the app origin').toEqual([])
})
