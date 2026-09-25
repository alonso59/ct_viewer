// VW-17/22/23 + UI-24 on the real backend: the same CT tools in Open mode and in a case tab
// (numeric W/L, slab, invert, HU probe, header info, measurements), and Close for both.
import { resolve } from 'node:path'

import { expect, test, type Page } from '@playwright/test'

import { gotoOpen } from './openMode'

const API = `http://127.0.0.1:${process.env.E2E_API_PORT ?? 8011}/api/v1`
const FIX = resolve(import.meta.dirname, '../../.fixtures/synthetic')

async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, { method, headers: { 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${await r.text()}`)
  return (r.status === 204 ? null : await r.json()) as T
}

async function useTools(page: Page, bar: ReturnType<Page['getByRole']>) {
  // numeric W/L drives the window
  await bar.getByLabel('Window width').fill('1500')
  await bar.getByLabel('Window level').fill('-600')
  await expect(bar.getByLabel('Window width')).toHaveValue('1500')
  // slab MIP with a thickness, then invert
  await bar.getByRole('button', { name: 'Slab projection' }).click()
  await page.getByRole('menuitem', { name: 'MIP' }).click()
  await expect(bar.getByLabel('Slab thickness in mm')).toHaveValue('10')
  await bar.getByRole('button', { name: 'Invert' }).click()
  await expect(bar.getByRole('button', { name: 'Invert' })).toHaveAttribute('aria-pressed', 'true')
  // HU probe over the axial tile
  const axial = page.locator('[data-tile="axial"]')
  const box = (await axial.boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await expect(page.getByRole('status', { name: 'Value under the cursor' })).toBeVisible()
  // a distance measurement: two clicks on the axial tile
  await bar.getByRole('button', { name: 'Distance' }).click()
  await page.mouse.click(box.x + box.width * 0.4, box.y + box.height * 0.5)
  await page.mouse.click(box.x + box.width * 0.6, box.y + box.height * 0.5)
  await expect(page.locator('.vp-measure text').first()).toContainText('mm')
  await bar.getByRole('button', { name: 'Clear measurements' }).click()
  await expect(page.locator('.vp-measure text')).toHaveCount(0)
  // header info
  await bar.getByRole('button', { name: 'Header info' }).click()
  const header = page.getByRole('dialog', { name: /Header/ })
  await expect(header.getByText('Shape (voxels)')).toBeVisible()
  return header
}

test('Open mode on DICOM has the CT tool set, DICOM tags and Close', async ({ page }) => {
  await gotoOpen(page, `${FIX}/dicom/P900`)
  const bar = page.getByRole('toolbar').filter({ has: page.getByRole('button', { name: 'Invert' }) })
  await expect(bar).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.vp').first()).toBeVisible()
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })
  const header = await useTools(page, bar)
  await header.getByRole('button', { name: 'Show DICOM tags' }).click()
  await expect(header.getByText(/\(0010,0020\)/)).toBeVisible()
  await page.keyboard.press('Escape')
  // UI-24: Close drops the session and returns home
  await page.getByRole('toolbar', { name: /actions/i }).getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
})

test('a case tab has the same tools; Close project returns to the workspace home', async ({ page }) => {
  const p = await api<{ project_id: string }>('POST', '/projects', { name: `CT tools ${Date.now()}`, packs: ['ccrcc'] })
  const pv = await api<{ preview_id: string }>('POST', `/projects/${p.project_id}/imports/preview`, { root: `${FIX}/Dataset900`, alias: 'DATA', detect: true })
  await api('POST', `/projects/${p.project_id}/imports`, { preview_id: pv.preview_id })
  await expect.poll(async () => (await api<{ index: { state: string } }>('GET', `/projects/${p.project_id}/imports`)).index.state, { timeout: 30_000 }).toBe('ready')
  await page.goto(`/p/${p.project_id}/case/case_00001`)
  const bar = page.getByRole('toolbar', { name: 'Tool bar' })
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })
  await expect(bar.getByRole('button', { name: 'Invert' })).toBeEnabled()
  const header = await useTools(page, bar)
  await page.keyboard.press('Escape')
  await expect(header).toBeHidden()
  await page.keyboard.press('ControlOrMeta+Shift+p')
  const palette = page.getByRole('dialog')
  await palette.getByRole('combobox').fill('Close project')
  await palette.getByRole('option', { name: /Close project/ }).click()
  await expect(page).toHaveURL(/\/$/)
})
