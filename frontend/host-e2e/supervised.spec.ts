// U1/J2/J3/J5/J6: real HTTP API + user-service supervisor; no CUDA or native nnU-Net inference.
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { expect, test } from '@playwright/test'

const fixture = JSON.parse(readFileSync(process.env.RW_BROWSER_ACCEPTANCE!, 'utf8')) as { root: string; workspace: string; source: string; derived: string; state: string }
const api = async (method: string, path: string, body?: unknown) => {
  const r = await fetch(`${process.env.RW_HOST_URL}/api/v1${path}`, { method, headers: { 'content-type': 'application/json', 'X-Reviewer': 'host browser acceptance' }, body: body === undefined ? undefined : JSON.stringify(body) })
  if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${await r.text()}`)
  return r.status === 204 ? null : r.json()
}

test('reconnect and API restart keep one attempt; pause, resume, cancel and archive acknowledge cleanup', async ({ page }) => {
  const { project_id: pid } = await api('POST', '/projects', { name: `Host browser ${Date.now()}` })
  const { preview_id: preview } = await api('POST', `/projects/${pid}/imports/preview`, { root: fixture.source, alias: 'DATA', detect: true })
  const imported = await api('POST', `/projects/${pid}/imports`, { preview_id: preview })
  await expect.poll(async () => (await api('GET', `/jobs/${imported.job_id}`)).status).toBe('succeeded')
  await api('PUT', `/projects/${pid}/roots/DERIVED`, { path: fixture.derived, role: 'derived' })
  const path = `/p/${pid}/tasks/segment.threshold`
  await page.goto(path)
  await page.getByRole('radio', { name: 'Item list' }).click()
  await page.getByText('Paste or edit item IDs').click()
  await page.getByPlaceholder('Item ids, separated by spaces, commas or new lines').fill('case_00001.01.complete.-')
  await expect(page.getByText('1 of 1 ready')).toBeVisible()
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  let row = page.locator('.task-run').first()
  await expect(row.getByText('Running', { exact: true })).toBeVisible({ timeout: 30_000 })
  const [run] = await api('GET', `/projects/${pid}/task-runs`)
  const attemptPath = join(fixture.workspace, 'queue', run.job_id, 'attempt.json')
  const attempt = JSON.parse(readFileSync(attemptPath, 'utf8')).attempt
  await page.goto('/')
  writeFileSync(join(fixture.root, 'restart.request'), '')
  await expect.poll(() => existsSync(join(fixture.root, 'restart.request')), { timeout: 30_000 }).toBe(false)
  await page.goto(path)
  row = page.locator('.task-run').first()
  await expect(row.getByText('Running', { exact: true })).toBeVisible({ timeout: 30_000 })
  expect((await api('GET', `/projects/${pid}/task-runs`)).map((r: { job_id: string }) => r.job_id)).toEqual([run.job_id])
  expect(JSON.parse(readFileSync(attemptPath, 'utf8')).attempt).toBe(attempt)
  await row.getByRole('button', { name: 'Pause', exact: true }).click()
  await expect(row.getByText('Paused', { exact: true })).toBeVisible({ timeout: 30_000 })
  expect(existsSync(join(fixture.state, 'lease.json'))).toBe(false)
  const stopped = JSON.parse(readFileSync(join(fixture.workspace, 'queue', run.job_id, 'exit.json'), 'utf8'))
  expect(stopped.cleanup_verified).toBe(true)
  await row.getByRole('button', { name: 'Resume', exact: true }).click()
  await expect(row.getByText('Running', { exact: true })).toBeVisible({ timeout: 30_000 })
  const [resumed] = await api('GET', `/projects/${pid}/task-runs`)
  expect(resumed.run_id).toBe(run.run_id)
  expect(resumed.job_id).not.toBe(run.job_id)
  writeFileSync(join(fixture.workspace, 'queue', resumed.job_id, 'continue'), '')
  await expect(row.getByText('Completed', { exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(row.getByText('Segmentation set', { exact: true })).toBeVisible()
  expect(existsSync(join(fixture.state, 'lease.json'))).toBe(false)
  await row.getByRole('button', { name: 'Archive', exact: true }).click()
  await expect(page.locator('.task-run')).toHaveCount(0)
  await page.getByRole('button', { name: 'Show archived runs' }).click()
  await expect(page.locator('.task-run').getByText('Completed', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Hide archived runs' }).click()
  await page.getByRole('radio', { name: 'Item list' }).click()
  await page.getByText('Paste or edit item IDs').click()
  await page.getByPlaceholder('Item ids, separated by spaces, commas or new lines').fill('case_00001.01.complete.-')
  await expect(page.getByText('1 of 1 ready')).toBeVisible()
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  row = page.locator('.task-run').first()
  await expect(row.getByText('Running', { exact: true })).toBeVisible({ timeout: 30_000 })
  await row.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(row.getByText('Cancelled', { exact: true })).toBeVisible({ timeout: 30_000 })
  expect(existsSync(join(fixture.state, 'lease.json'))).toBe(false)
})
