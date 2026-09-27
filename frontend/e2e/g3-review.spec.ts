// G3 review journey (VISION §Journeys, REL-02; started in FB3): open a project → first case →
// A → Alt+↓ → A (both recorded, AUD-A2-02, CUR-04) → next unreviewed case (AUD-A1-04, CUR-08) →
// open from the correction queue and follow its navigation context (AUD-A1-04, CUR-09) → browser
// Back returns to the previous case (AUD-A1-02, FE-04) → the Explorer shows the active case
// (AUD-A1-03, UI-08) → the queue exports as CSV with the segmentation set (CUR-09/10) → one-click
// phase in the case header (PHS-01) → a decision with a comment on the set on screen (CUR-05,
// VW-19; AUD-A6-16). Title-bar entry points (menus, quick open, share, About) are used too,
// because browsers may reserve Ctrl/Cmd+P and Ctrl/Cmd+W (UI-05, AUD-A1-09/11, NFR-16).
// Real backend on the synthetic fixtures; setup goes through the API.

import { readFileSync } from 'node:fs'

import { expect, test, type Page } from '@playwright/test'

import { api, importedProject } from './helpers'

interface CaseRow { case_id: string; review_state: string; excluded?: boolean }
const events = async (pid: string, caseId: string) =>
  (await api<{ items: { status: string; reviewer: string }[] }>('GET', `/projects/${pid}/curation/events?case_id=${caseId}`)).items

/** The case tab shows `caseId` with its item loaded (the item switcher renders after the case detail) */
async function onCase(page: Page, pid: string, caseId: string) {
  await expect(page).toHaveURL(new RegExp(`/p/${pid}/case/${caseId}(\\?|$)`))
  const header = page.locator('.case-header').filter({ has: page.locator('.case-id', { hasText: caseId }) })
  await expect(header.getByRole('toolbar', { name: 'Item' })).toBeVisible()
}

test.setTimeout(120_000)

test('G3: review loop with the keyboard, review order and history', async ({ page, browserName }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  const pid = await importedProject(`G3 ${browserName} ${Date.now()}`)
  const cases = (await api<{ items: CaseRow[] }>('GET', `/projects/${pid}/cases?limit=500`)).items
  const [first, second] = cases
  expect(first && second).toBeTruthy()

  await page.addInitScript(() => localStorage.setItem('rw.reviewer', JSON.stringify({ state: { name: 'Dr. G3' }, version: 0 })))
  await page.goto(`/p/${pid}`)

  // First case from the Explorer; A records a decision
  const tree = page.getByRole('tree', { name: 'Project' })
  await tree.getByRole('treeitem', { name: new RegExp(first!.case_id) }).dblclick()
  await onCase(page, pid, first!.case_id)
  await page.keyboard.press('a')
  await expect.poll(async () => (await events(pid, first!.case_id)).length).toBe(1)

  // Alt+↓ → the next case; A works again without clicking the image (AUD-A2-02)
  await page.keyboard.press('Alt+ArrowDown')
  await onCase(page, pid, second!.case_id)
  await page.keyboard.press('a')
  await expect.poll(async () => (await events(pid, second!.case_id)).map((e) => e.status)).toEqual(['accepted'])
  expect((await events(pid, first!.case_id)).length).toBe(1)

  // Next unreviewed case (Alt+Shift+↓): the next case that is not fully reviewed (CUR-08)
  const after = (await api<{ items: CaseRow[] }>('GET', `/projects/${pid}/cases?limit=500`)).items
  const i = after.findIndex((c) => c.case_id === second!.case_id)
  const expected = [...after.slice(i + 1), ...after.slice(0, i + 1)].find((c) => c.review_state !== 'reviewed' && !c.excluded && c.case_id !== second!.case_id)
  await page.keyboard.press('Alt+Shift+ArrowDown')
  await onCase(page, pid, expected!.case_id)

  // Two items in the correction queue; open the queue from the title-bar Go menu
  const q1 = after.at(-3)!.case_id
  const q2 = after.at(-2)!.case_id
  for (const cid of [q1, q2]) {
    const detail = await api<{ scans: { items: { item_id: string; scope: string; status: string }[] }[] }>('GET', `/projects/${pid}/cases/${cid}`)
    const items = detail.scans.flatMap((x) => x.items)
    const item = items.find((x) => x.scope === 'complete' && x.status === 'active') ?? items[0]
    await api('POST', `/projects/${pid}/curation/events`, { item_id: item!.item_id, target: 'seg', status: 'needs_minor_correction', add_to_queue: true })
  }
  await page.getByRole('navigation', { name: 'Application menu' }).getByRole('button', { name: 'Go' }).click()
  await page.getByRole('menuitem', { name: 'Open correction queue' }).click()
  const rows = page.locator('table tbody tr[data-clickable]')
  await expect(rows).toHaveCount(2)
  const firstQ = (await rows.nth(0).locator('td').first().textContent()) ?? ''
  const secondQ = (await rows.nth(1).locator('td').first().textContent()) ?? ''
  expect([firstQ, secondQ].sort()).toEqual([q1, q2].sort())
  // Queue export (CUR-10): a CSV for 3D Slicer with one row per queued decision and its set
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export CSV for 3D Slicer' }).click()
  const csv = readFileSync((await (await download).path())!, 'utf-8').trim().split('\n')
  expect(csv[0]).toContain('seg_id')
  expect(csv.slice(1).map((l) => l.split(',')[0]).sort()).toEqual([q1, q2].sort())
  await rows.nth(0).click()
  await onCase(page, pid, firstQ)
  const chip = page.getByRole('group', { name: 'Navigation list: Correction queue' })
  await expect(chip).toContainText('Correction queue 1/2')

  // Alt+↓ follows the queue, not the Explorer order
  await page.keyboard.press('Alt+ArrowDown')
  await onCase(page, pid, secondQ)
  await expect(chip).toContainText('Correction queue 2/2')

  // Browser Back returns to the previous case, inside the project (AUD-A1-02)
  await page.goBack()
  await onCase(page, pid, firstQ)
  await expect(chip).toContainText('Correction queue 1/2')

  // The Explorer shows and selects the active case (AUD-A1-03)
  // (the Project view is still the side bar's view; clicking its icon again would hide it)
  if (!(await tree.isVisible())) await page.getByRole('navigation', { name: 'Activity bar' }).getByRole('button', { name: 'Project', exact: true }).click()
  const active = tree.getByRole('treeitem', { name: new RegExp(firstQ) })
  await expect(active).toBeVisible()
  await expect(active).toHaveAttribute('aria-selected', 'true')

  // × falls back to Explorer order
  await chip.getByRole('button', { name: 'Back to Explorer order' }).click()
  await expect(chip).toHaveCount(0)

  // One-click phase (PHS-01): the case header's control sets the scan's phase at once
  const scan = (await api<{ scans: { scan_idx: string; items: { scope: string; phase: { canonical: string } }[] }[] }>('GET', `/projects/${pid}/cases/${firstQ}`)).scans[0]!
  const now = scan.items.find((x) => x.scope === 'complete')!.phase.canonical
  const pick = now === 'EP' ? 'NC' : 'EP'
  const phase = page.locator('.case-header').getByRole('group', { name: `Phase of ${firstQ} · ${scan.scan_idx}` })
  await phase.getByRole('button', { name: pick, exact: true }).click()
  await expect(phase.getByRole('button', { name: pick, exact: true })).toHaveAttribute('aria-pressed', 'true')
  const selections = await api<{ items: { value: string; reviewer: string }[] }>('GET', `/projects/${pid}/phase/events?case_id=${firstQ}&scan_idx=${scan.scan_idx}`)
  expect(selections.items.map((e) => [e.value, e.reviewer])).toEqual([[pick, 'Dr. G3']])

  // A decision with a comment (CUR-05), recorded on the segmentation set on screen (VW-19)
  const bar2 = page.getByRole('navigation', { name: 'Activity bar' })
  await bar2.getByRole('button', { name: 'Curation', exact: true }).click()
  const form = page.getByRole('complementary', { name: 'Curation' })
  await form.getByPlaceholder('What is wrong, and where (slices)?').fill('Leak at the upper pole, slices 20-24')
  await form.getByRole('button', { name: /^Minor/ }).click()
  await expect
    .poll(async () => (await api<{ items: { comment: string; seg_id: string | null; status: string }[] }>('GET', `/projects/${pid}/curation/events?case_id=${firstQ}`)).items.find((e) => e.comment))
    .toMatchObject({ comment: 'Leak at the upper pole, slices 20-24', seg_id: 'imported', status: 'needs_minor_correction' })

  // Title-bar entry points: quick open, share menu, Help › About (NFR-16)
  await page.getByRole('button', { name: /Go to case/ }).click()
  const quick = page.getByRole('dialog')
  await quick.getByRole('combobox').fill(first!.case_id)
  await quick.getByRole('option', { name: new RegExp(first!.case_id) }).first().click()
  await onCase(page, pid, first!.case_id)
  await page.getByRole('button', { name: 'Share' }).click()
  await page.getByRole('menuitem', { name: 'Copy edit link' }).click()
  await expect(page.getByRole('status').filter({ hasText: new RegExp(`/p/${pid}/case/${first!.case_id}`) }).first()).toBeVisible()
  await page.getByRole('navigation', { name: 'Application menu' }).getByRole('button', { name: 'Help' }).click()
  await page.getByRole('menuitem', { name: 'About' }).click()
  await expect(page.getByRole('dialog', { name: 'About' })).toContainText('Research use only')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'About' })).toHaveCount(0)

  expect(errors).toEqual([])
})
