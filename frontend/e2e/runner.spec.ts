// TST-14 in CI (ADR-0016 §8): the fake `segment.threshold` plugin runs through the file queue and
// the real host runner (scripts/rw-runner.py), and adds a segmentation set; curation decisions then
// name the set on screen (VW-19, AUD-A5-05/06). Real backend.
import { spawn, type ChildProcess } from 'node:child_process'
import { resolve } from 'node:path'

import { expect, test } from '@playwright/test'

import { api, importedProject } from './helpers'

const REPO = resolve(import.meta.dirname, '../..')
const ITEM = 'case_00001.01.complete.-'

let runner: ChildProcess | null = null
test.afterEach(() => {
  runner?.kill('SIGTERM')
  runner = null
})

test('the fake segmentation plugin adds a set through the host runner', async ({ page }) => {
  test.setTimeout(120_000)
  const pid = await importedProject(`Runner ${Date.now()}`)
  await api('PUT', `/projects/${pid}/roots/DERIVED`, { path: process.env.E2E_DERIVED, role: 'derived' })

  await page.goto(`/p/${pid}/tasks/segment.threshold`)
  await expect(page.getByRole('heading', { name: 'Threshold segmentation (test)' })).toBeVisible()
  await page.getByRole('radio', { name: 'Item list' }).click()
  await page.getByPlaceholder('Item ids, separated by spaces, commas or new lines').fill(ITEM)
  await expect(page.getByText('1 of 1 ready')).toBeVisible()
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  const row = page.locator('.task-run').first()
  await expect(row.getByText('Waiting for runner', { exact: true })).toBeVisible({ timeout: 15_000 })

  const health = await api<{ ui_config: unknown }>('GET', '/health')
  expect(health).toBeTruthy()
  const workspace = process.env.E2E_WORKSPACE ?? ''
  runner = spawn(resolve(REPO, 'backend/.venv/bin/python'), [resolve(REPO, 'scripts/rw-runner.py'), '--workspace', workspace, '--plugins', process.env.E2E_PLUGINS ?? '', '--poll', '0.2'], { stdio: 'ignore' })
  await expect(row.getByText('Completed', { exact: true })).toBeVisible({ timeout: 45_000 })
  await expect(row.getByText('Segmentation set')).toBeVisible()
  const sets = await api<{ seg_id: string; kind: string; n_items: number }[]>('GET', `/projects/${pid}/segmentations`)
  expect(sets.filter((s) => s.kind === 'task').map((s) => s.n_items)).toEqual([1])
  const segId = sets.find((s) => s.kind === 'task')?.seg_id ?? ''

  // VW-19 / ADR-0015 (AUD-A5-05, A5-06): decisions name the set on screen, per project
  await page.evaluate(() => localStorage.setItem('rw.reviewer', JSON.stringify({ state: { name: 'Dr. S' }, version: 0 })))
  await page.goto(`/p/${pid}/case/case_00001?item=${encodeURIComponent(ITEM)}`)
  // ADR-0028: the inspector is in the title bar's Layout menu
  await page.getByRole('banner').getByRole('button', { name: /^Layout/ }).click()
  await page.getByRole('menuitemcheckbox', { name: /Inspector/ }).click()
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
