// TST-14 in CI (ADR-0016 §8): the fake `segment.threshold` plugin runs through the file queue and
// the real host runner (scripts/rw-runner.py), and adds a segmentation set; curation decisions then
// name the set on screen (VW-19, AUD-A5-05/06). Real backend.
import { spawn, type ChildProcess } from 'node:child_process'
import { resolve } from 'node:path'

import { expect, test } from '@playwright/test'

const API = `http://127.0.0.1:${process.env.E2E_API_PORT ?? 8011}/api/v1`
const REPO = resolve(import.meta.dirname, '../..')
const DATASET = resolve(REPO, '.fixtures/synthetic/Dataset900')
const ITEM = 'case_00001.01.complete.-'

async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, { method, headers: { 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${await r.text()}`)
  return (await r.json()) as T
}

let runner: ChildProcess | null = null
test.afterEach(() => {
  runner?.kill('SIGTERM')
  runner = null
})

test('the fake segmentation plugin adds a set through the host runner', async ({ page }) => {
  test.setTimeout(120_000)
  const p = await api<{ project_id: string }>('POST', '/projects', { name: `Runner ${Date.now()}`, packs: ['ccrcc'] })
  const pid = p.project_id
  const pv = await api<{ preview_id: string }>('POST', `/projects/${pid}/imports/preview`, { root: DATASET, alias: 'DATA', detect: true })
  await api('POST', `/projects/${pid}/imports`, { preview_id: pv.preview_id })
  await expect.poll(async () => (await api<{ index: { state: string } }>('GET', `/projects/${pid}/imports`)).index.state, { timeout: 30_000 }).toBe('ready')
  await api('PUT', `/projects/${pid}/roots/DERIVED`, { path: process.env.E2E_DERIVED, role: 'derived' })

  await page.goto(`/p/${pid}/tasks/segment.threshold`)
  await expect(page.getByRole('heading', { name: 'Threshold segmentation (test)' })).toBeVisible()
  await page.getByRole('radio', { name: 'Item list' }).click()
  await page.getByPlaceholder('Item ids, separated by spaces, commas or new lines').fill(ITEM)
  await expect(page.getByText('1 of 1 ready')).toBeVisible()
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  const row = page.locator('.task-run').first()
  await expect(row.getByText('waiting for runner', { exact: true })).toBeVisible({ timeout: 15_000 })

  const health = await api<{ ui_config: unknown }>('GET', '/health')
  expect(health).toBeTruthy()
  const workspace = process.env.E2E_WORKSPACE ?? ''
  runner = spawn(resolve(REPO, 'backend/.venv/bin/python'), [resolve(REPO, 'scripts/rw-runner.py'), '--workspace', workspace, '--plugins', process.env.E2E_PLUGINS ?? '', '--poll', '0.2'], { stdio: 'ignore' })
  await expect(row.getByText('completed', { exact: true })).toBeVisible({ timeout: 45_000 })
  await expect(row.getByText('Segmentation set')).toBeVisible()
  const sets = await api<{ seg_id: string; kind: string; n_items: number }[]>('GET', `/projects/${pid}/segmentations`)
  expect(sets.filter((s) => s.kind === 'task').map((s) => s.n_items)).toEqual([1])
  const segId = sets.find((s) => s.kind === 'task')?.seg_id ?? ''

  // VW-19 / ADR-0015 (AUD-A5-05, A5-06): decisions name the set on screen, per project
  await page.evaluate(() => localStorage.setItem('rw.reviewer', JSON.stringify({ state: { name: 'Dr. S' }, version: 0 })))
  await page.goto(`/p/${pid}/case/case_00001?item=${encodeURIComponent(ITEM)}`)
  await page.getByRole('banner').getByRole('button', { name: 'Toggle inspector' }).click()
  const inspector = page.locator('.inspector')
  await inspector.getByLabel('Segmentation set').selectOption(segId)
  await inspector.getByRole('button', { name: /^Accept/ }).first().click()
  const seg = async (item: string) => {
    const st = await api<{ items: { item_id: string; targets: { target: string; seg_id: string | null; status: string }[] }[] }>('GET', `/projects/${pid}/curation/state`)
    return st.items.find((i) => i.item_id.startsWith(item))?.targets.filter((x) => x.target === 'seg').map((x) => `${x.seg_id}:${x.status}`) ?? []
  }
  await expect.poll(() => seg(ITEM)).toEqual([`${segId}:accepted`])
  await expect(inspector.getByRole('list', { name: 'Current decisions' })).toContainText('Accepted')
  // the default set's decision is its own row: the task set's one does not show for `imported`
  await inspector.getByLabel('Segmentation set').selectOption('imported')
  await expect(inspector.getByRole('list', { name: 'Current decisions' })).toHaveCount(0)
  await inspector.getByLabel('Segmentation set').selectOption(segId)
  // an item without a mask in the chosen set shows the default one with a notice; its decision is
  // about the mask on screen (no 422)
  // (the choice lives in the page, so move within the app)
  const tree = page.getByRole('tree', { name: 'Project' })
  if (!(await tree.isVisible())) await page.getByRole('navigation', { name: 'Activity bar' }).getByRole('button', { name: 'Project', exact: true }).click()
  await tree.getByRole('treeitem', { name: /case_00002/ }).dblclick()
  await expect(page.locator('.case-header').getByRole('note')).toContainText('Not in set')
  await inspector.getByRole('button', { name: /^Accept/ }).first().click()
  await expect.poll(() => seg('case_00002.')).toEqual(['imported:accepted'])
  await expect(page.getByRole('status').filter({ hasText: 'failed' })).toHaveCount(0)
})
