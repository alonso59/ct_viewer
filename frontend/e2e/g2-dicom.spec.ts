// Journey G2 (VISION, REL-02) on the real backend: Convert DICOM overlay → dry run lists the
// skipped series with its reason → run → Create project → wizard → Explorer with phases and
// warnings → Problems opens the item → its DICOM tags are readable; the dataset is on the home.
// UI-25, DCM-04/06/14, TSK-13, SRC-16, UI-09, VW-22; AUD-A2-04, A2-10, A2-13, A2-14, A1-15 (FB4).
import { expect, test } from '@playwright/test'

import { gotoOpen } from './openMode'

const API = `http://127.0.0.1:${process.env.E2E_API_PORT ?? 8011}/api/v1`

test('G2: convert DICOM, make a project, review phases and problems, read the DICOM tags', async ({ page, browserName }) => {
  test.setTimeout(150_000)
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  const name = `g2-${browserName}-${Date.now()}`

  await page.goto('/')
  await page.getByRole('button', { name: /Convert DICOM/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Convert DICOM' })
  const folders = dialog.getByRole('listbox', { name: 'Folders' })
  await folders.getByRole('button', { name: /synthetic/ }).click()
  await folders.getByRole('button', { name: /^dicom$/ }).click()
  await dialog.getByRole('button', { name: 'Next' }).click()
  await dialog.getByLabel('Dataset name').fill(name)
  await dialog.getByRole('button', { name: 'Dry run' }).click()

  // DCM-06 (AUD-A2-13): every series, the skipped one with its reason, sizes with their unit
  const plan = dialog.locator('details.conv-plan')
  await expect(plan.locator('summary')).toHaveText(/^\d+ series · 1 skipped$/)
  if (!(await plan.getAttribute('open'))) await plan.locator('summary').click()
  const skipped = plan.locator('tr[data-action="skip"]')
  await expect(skipped).toHaveCount(1)
  await expect(skipped).toContainText('Skip: localizer / scout')
  await expect(plan.locator('tr[data-action="convert"]').first()).toContainText(/\d+(\.\d)? (KB|MB)/)
  await dialog.getByRole('button', { name: /Convert \d+ series/ }).click()
  await dialog.getByRole('button', { name: 'Show the result' }).click({ timeout: 60_000 })
  await expect(dialog.getByText(`Dataset ${name} is ready.`)).toBeVisible()
  const runs = (await (await fetch(`${API}/task-runs`)).json()) as { name: string; dataset_dir: string }[]
  const dataset = runs.find((r) => r.name === name)?.dataset_dir ?? ''
  expect(dataset).toContain(`/_datasets/${name}`)

  // Create project → wizard on the dataset: the metadata table, in plain words (AUD-A1-15)
  await dialog.getByRole('button', { name: 'Create project from this' }).click()
  const create = page.getByRole('dialog', { name: 'New project' })
  await create.getByLabel('Project name').fill(`G2 ${name}`)
  await create.getByRole('button', { name: 'Create and import' }).click()
  await expect(page).toHaveURL(/\/p\/[0-9A-Z]{26}/)
  const pid = /\/p\/([0-9A-Z]{26})/.exec(page.url())?.[1] ?? ''
  const wizard = page.getByRole('dialog', { name: 'Import data' })
  await expect(wizard.getByRole('radio', { name: /Metadata table \(metadata\.jsonl\)/ })).toBeChecked()
  await wizard.getByRole('button', { name: 'Next' }).click()
  await wizard.getByRole('button', { name: 'Import and index' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Import finished' })).toBeVisible({ timeout: 30_000 })

  // Explorer: the cases with their phases (the chained analyzer's layer) and warning badges
  const tree = page.getByRole('tree', { name: 'Project' })
  await expect(tree.getByRole('treeitem', { name: /case_00000/ })).toBeVisible()
  await expect(tree.getByRole('treeitem', { name: /case_00001/ })).toBeVisible()
  const item = (await (await fetch(`${API}/projects/${pid}/items/case_00000.01.complete.-`)).json()) as { phase: { canonical: string } }
  expect(item.phase.canonical).toBe('NP')
  await tree.getByRole('treeitem', { name: /case_00000/ }).click()
  await expect(tree.getByText('NP').first()).toBeVisible()

  // Problems → the item opens in its case tab (UI-09)
  await page.getByRole('tab', { name: /Problems/ }).click()
  const problem = page.getByRole('tabpanel').getByRole('treeitem').filter({ hasText: 'case_00000' }).first()
  await expect(problem).toBeVisible()
  await problem.click()
  await expect(page).toHaveURL(new RegExp(`/p/${pid}/case/case_00000`))
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })

  // DICOM tags readable in the project (AUD-A2-04: the dataset's relative sidecar refs)
  const bar = page.getByRole('toolbar', { name: 'Tool bar' })
  await bar.getByRole('button', { name: 'Header info' }).click()
  const header = page.getByRole('dialog', { name: /Header/ })
  await header.getByRole('button', { name: 'Show DICOM tags' }).click()
  await expect(header.getByText(/\(0010,0020\)/)).toBeVisible()
  await expect(header.getByRole('alert')).toHaveCount(0)
  await page.keyboard.press('Escape')

  // The dataset has a home (AUD-A2-14), and Open mode knows its modality (AUD-A2-10)
  await page.goto('/')
  const recent = page.getByRole('list', { name: 'Converted datasets' })
  await expect(recent.getByRole('listitem').filter({ hasText: name })).toBeVisible()
  await gotoOpen(page, dataset)
  await expect(page.locator('.case-loading')).toHaveCount(0, { timeout: 30_000 })
  await expect(page.getByText(/\(assumed\)/)).toHaveCount(0)
  expect(errors).toEqual([])
})
