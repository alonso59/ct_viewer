// Journey G1 (VISION, REL-02) on the real backend: Home → open one NIfTI without a project → W/L,
// HU probe with its unit inside the hovered view, fit → attach its label map from the sibling
// `seg/` folder → Save as NIfTI → Create project from this (the mask travels) → Close.
// SRC-09/10/14/05, VW-05/08/22/26, UI-17/24; AUD-A2-03, A2-11, A2-12, A3-05, A1-16 (FB4).
import { expect, test, type Page } from '@playwright/test'

import { API } from './helpers'

const IMAGE = '01_case_00030_0000.nii.gz'
const MASK = '01_case_00030.nii.gz'

const view = (page: Page, name: string) => page.getByRole('region', { name, exact: true })

test('G1: open a NIfTI, inspect it, attach its label map, save, make a project, close', async ({ page, browserName }) => {
  test.setTimeout(120_000)
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))

  // Home → Open file or folder…; a long folder has a filter (AUD-A1-16)
  await page.goto('/')
  await page.getByRole('button', { name: /Open file or folder/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Open file or folder' })
  const folders = dialog.getByRole('listbox', { name: 'Folders' })
  await folders.getByRole('button', { name: /synthetic/ }).click()
  await expect(folders.getByRole('button', { name: 'Parent folder' })).toHaveCount(0) // a shared root
  await folders.getByRole('button', { name: /Dataset900/ }).click()
  await folders.getByRole('button', { name: /^nifti$/ }).click()
  await dialog.getByRole('searchbox', { name: 'Filter this folder' }).fill('00030')
  await folders.getByRole('button', { name: IMAGE }).click()
  await dialog.getByRole('button', { name: 'Open file' }).click()
  await expect(page).toHaveURL(/\/open\/[0-9A-Z]{26}$/)
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })

  // W/L: the CT default on open (VW-05, AUD-A6-16), then a numeric window (VW-22)
  const bar = page.getByRole('toolbar').filter({ has: page.getByRole('button', { name: 'Invert' }) })
  await expect(bar.getByLabel('Window width')).toHaveValue('400')
  await expect(bar.getByLabel('Window level')).toHaveValue('50')
  await bar.getByLabel('Window width').fill('1500')
  await bar.getByLabel('Window level').fill('-600')
  await expect(view(page, 'Axial').locator('.vp-corner-tl')).toContainText('1500')

  // HU probe: value with its unit, ijk and RAS mm, inside the hovered view (AUD-A2-11, A3-05)
  const axial = view(page, 'Axial').locator('.vp-body')
  const box = (await axial.boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  const probe = view(page, 'Axial').getByRole('status', { name: 'Value under the cursor' })
  await expect(probe).toHaveText(/^-?\d+(\.\d+)? HU · (.+ · )?ijk \d+, \d+, \d+ · RAS .+ mm$/)
  await expect(view(page, 'Coronal').getByRole('status', { name: 'Value under the cursor' })).toHaveCount(0)

  // Fit (VW-26): zoom the axial view, then fit it back to 100 %
  await page.keyboard.down('Control')
  await page.mouse.wheel(0, -300)
  await page.keyboard.up('Control')
  await expect(view(page, 'Axial').locator('.vp-corner-tr')).toHaveText(/\d+ %/)
  await view(page, 'Axial').getByRole('button', { name: 'Fit to window' }).click()
  await expect(view(page, 'Axial').locator('.vp-corner-tr')).toHaveCount(0)

  // Attach the label map from the sibling seg/ folder: the browser starts there (AUD-A2-03)
  const actions = page.getByRole('toolbar', { name: 'Open-mode actions' })
  await actions.getByRole('button', { name: 'Attach segmentation…' }).click()
  const attach = page.getByRole('dialog', { name: 'Attach a segmentation' })
  await expect(attach.locator('.fs-path')).toContainText(/Dataset900\/seg$/)
  await attach.getByRole('searchbox', { name: 'Filter this folder' }).fill('00030')
  await attach.getByRole('listbox', { name: 'Folders' }).getByRole('button', { name: MASK }).click()
  await attach.getByRole('button', { name: 'Attach', exact: true }).click()
  await expect(attach).toBeHidden()
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })
  await expect(page.locator('.vp-notice')).toHaveCount(0) // the mask loaded
  await expect(view(page, '3D').getByText('No segmentation')).toHaveCount(0)

  // Save as NIfTI (SRC-14)
  await actions.getByRole('button', { name: 'Save as NIfTI…' }).click()
  const save = page.getByRole('dialog', { name: /Save .* as NIfTI/ })
  await save.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: /Saved .*01_case_00030_0000(-\d+)?\.nii\.gz/ })).toBeVisible({ timeout: 30_000 })
  const openUrl = page.url()

  // Create project from this: the attached mask and the file naming travel (AUD-A2-12)
  await actions.getByRole('button', { name: 'Create project from this' }).click()
  const create = page.getByRole('dialog', { name: 'New project' })
  await create.getByLabel('Project name').fill(`G1 ${browserName} ${Date.now()}`)
  await create.getByRole('button', { name: 'Create and import' }).click()
  await expect(page).toHaveURL(/\/p\/[0-9A-Z]{26}/)
  const pid = /\/p\/([0-9A-Z]{26})/.exec(page.url())?.[1] ?? ''
  const wizard = page.getByRole('dialog', { name: 'Import data' })
  await expect(wizard.getByRole('radio', { name: /NIfTI files/ })).toBeChecked()
  await expect(wizard.getByRole('note').filter({ hasText: `seg/${MASK}` })).toBeVisible()
  await expect(wizard.getByLabel('File name pattern')).toHaveValue(/\(\?P<scan_idx>/)
  await wizard.getByRole('button', { name: 'Next' }).click()
  await wizard.getByRole('button', { name: 'Import and index' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Import finished' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('tree', { name: 'Project' }).getByRole('treeitem', { name: /case_00030/ })).toBeVisible()
  const item = (await (await fetch(`${API}/projects/${pid}/items/case_00030.01.complete.-`)).json()) as { masks: Record<string, { ref: string }> }
  expect(item.masks.imported?.ref).toBe(`DATA:seg/${MASK}`)
  const warnings = (await (await fetch(`${API}/projects/${pid}/warnings`)).json()) as { items: { code: string }[] }
  expect(warnings.items.map((w) => w.code)).toEqual([]) // no phase noise, no guessed seg path

  // Back to the Open session, then Close ends it and returns home (UI-24)
  await page.goto(openUrl)
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })
  await actions.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
  expect(errors).toEqual([])
})
